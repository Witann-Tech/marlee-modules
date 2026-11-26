import base64
import io
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import requests
from PIL import Image

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError

from odoo.addons.access_control_api.controllers.main import AccessControlApi


class TestAccessRecovery(TransactionCase):
    def setUp(self):
        super().setUp()
        self.site = self.env['access_control.site'].create({'name': 'Recovery QA', 'code': 'RECOVERY-QA'})
        self.devices = self.env['access_control.device'].create([
            {'name': name, 'device_serial': name, 'site_id': self.site.id} for name in ('RECOVERY-1', 'RECOVERY-2')
        ])
        image = io.BytesIO()
        Image.new('RGB', (400, 400), (90, 130, 170)).save(image, format='JPEG')
        self.partner = self.env['res.partner'].create({'name': 'Recovery QA', 'image_1920': base64.b64encode(image.getvalue()).decode()})
        self.person = self.env['access_control.person'].create({
            'partner_id': self.partner.id, 'active': True, 'site_ids': [(6, 0, self.site.ids)],
        })
        self.Request = self.env['access_control.resync_request'].sudo()
        self.protocol_patch = patch.object(type(self.Request), '_gateway_recovery_protocol', return_value=2)
        self.protocol_patch.start()
        self.addCleanup(self.protocol_patch.stop)

    def _queue(self, devices=None):
        return self.Request._queue_for_people(self.person, devices if devices is not None else self.devices,
                                              self.env.company, self.env.user)

    def _delta(self, device, cursor):
        controller = AccessControlApi()
        params = {'siteCode': self.site.code, 'deviceSerial': device.device_serial, 'cursor': cursor}
        with patch('odoo.addons.access_control_api.controllers.main.request', SimpleNamespace(env=self.env, params=params)), \
             patch.object(controller, '_auth_ok', return_value=(True, None)):
            return controller.sync_delta()

    def test_identical_photo_is_queued_for_each_selected_device_without_new_identity(self):
        before = (self.person.id, self.person.global_user_id, self.person.face_pic_b64)
        request = self._queue(self.devices[1])
        changes = self.env['access_control.sync_change'].search([('resync_target_id', 'in', request.target_ids.ids)])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes.device_id, self.devices[1])
        self.assertTrue(changes.include_face_pic)
        self.assertEqual(before, (self.person.id, self.person.global_user_id, self.person.face_pic_b64))

    def _detailed_photo(self):
        image = Image.new('RGB', (480, 640))
        image.putdata([((x * 17 + y * 13) % 256, (x * 3 + y * 31) % 256, (x * 29 + y * 7) % 256)
                       for y in range(640) for x in range(480)])
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=85)
        return base64.b64encode(buffer.getvalue()).decode()

    def test_three_doors_seal_the_same_final_photo_and_repeated_requests_do_not_recompress(self):
        self.devices |= self.env['access_control.device'].create({
            'name': 'RECOVERY-3', 'device_serial': 'RECOVERY-3', 'site_id': self.site.id})
        self.person.with_context(skip_access_sync_queue=True).write({'face_pic_b64': self._detailed_photo()})
        photo = self.person.face_pic_b64
        Partner = type(self.partner)
        original = Partner._prepare_biometric_face_b64
        calls = []
        def counted(partner, source, log_context=None):
            calls.append(log_context)
            return original(partner, source, log_context=log_context)
        with patch.object(Partner, '_prepare_biometric_face_b64', counted):
            first = self._queue()
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.person.face_pic_b64, photo)
        self.assertEqual(len(first.target_ids), 3)
        self.assertTrue(all(t.authorization_hash == t._current_authorization_hash() for t in first.target_ids))
        second = self._queue()
        self.assertEqual(self.person.face_pic_b64, photo)
        self.assertTrue(all(t.authorization_hash == t._current_authorization_hash() for t in first.target_ids | second.target_ids))
        for target in first.target_ids:
            self.assertTrue(target._recovery_metadata(self.person, target.device_id))

    def test_nine_people_three_doors_keep_all_twenty_seven_authorizations_valid(self):
        self.devices |= self.env['access_control.device'].create({
            'name': 'RECOVERY-3', 'device_serial': 'RECOVERY-3', 'site_id': self.site.id})
        people = self.person
        for number in range(8):
            partner = self.env['res.partner'].create({'name': 'Recovery batch %s' % number})
            people |= self.env['access_control.person'].create({
                'partner_id': partner.id, 'active': True, 'site_ids': [(6, 0, self.site.ids)],
                'face_pic_b64': self._detailed_photo()})
        before = people.read(['partner_id', 'global_user_id', 'face_pic_b64'])
        request = self.Request._queue_for_people(people, self.devices, self.env.company, self.env.user)
        self.assertEqual(len(request.target_ids), 27)
        self.assertEqual(before, people.read(['partner_id', 'global_user_id', 'face_pic_b64']))
        self.assertTrue(all(t.authorization_hash == t._current_authorization_hash() for t in request.target_ids))

    def test_v2_separates_queue_deadline_from_command_ttl_and_caps_authorization(self):
        now = fields.Datetime.now()
        deadline = now + timedelta(minutes=7)
        with patch('odoo.addons.access_control_api.models.access_resync.fields.Datetime.now', return_value=now):
            request = self.Request._queue_for_people(self.person, self.devices, self.env.company, self.env.user,
                authorization_expires_at=deadline)
        self.assertEqual(request.expires_at, deadline)
        self.assertEqual(request.protocol_version, 2)
        target = request.target_ids[0]
        metadata = target._recovery_metadata(self.person, target.device_id)
        self.assertEqual(metadata['protocolVersion'], 2)
        self.assertEqual(metadata['commandTtlSeconds'], 600)
        self.assertEqual(metadata['expiresAt'], deadline.isoformat(timespec='seconds')+'Z')

    def test_legacy_gateway_preserves_the_original_ten_minute_contract(self):
        with patch.object(type(self.Request), '_gateway_recovery_protocol', return_value=1):
            now = fields.Datetime.now()
            with patch('odoo.addons.access_control_api.models.access_resync.fields.Datetime.now', return_value=now):
                request = self._queue()
        self.assertEqual(request.expires_at, now+timedelta(minutes=10))
        target = request.target_ids[0]
        self.assertNotIn('protocolVersion', target._recovery_metadata(self.person, target.device_id))

    def _capability_response(self, session, payload=None, status=200):
        self.protocol_patch.stop()
        response = session.return_value.__enter__.return_value.get.return_value.__enter__.return_value
        response.status_code = status
        response.content = b'{}'
        response.json.return_value = payload or {'protocolVersions': [1, 2], 'maxQueueSeconds': 3600, 'maxCommandSeconds': 600}
        return response

    def test_capability_negotiation_closes_http_resources_and_selects_v2(self):
        with patch('odoo.addons.access_control_api.models.access_resync.requests.Session') as session:
            self._capability_response(session)
            request = self._queue()
            self.assertEqual(request.protocol_version, 2)
            session.return_value.__exit__.assert_called_once()
            session.return_value.__enter__.return_value.get.return_value.__exit__.assert_called_once()

    def test_capability_404_is_legacy_but_invalid_or_unreachable_gateway_never_silently_downgrades(self):
        with patch('odoo.addons.access_control_api.models.access_resync.requests.Session') as session:
            self._capability_response(session, status=404)
            self.assertEqual(self._queue().protocol_version, 1)
        for payload in ([], {'protocolVersions': [2], 'maxQueueSeconds': 1, 'maxCommandSeconds': 600}):
            with patch('odoo.addons.access_control_api.models.access_resync.requests.Session') as session:
                response = self._capability_response(session)
                response.json.return_value = payload
                count = self.Request.search_count([])
                with self.assertRaises(ValidationError):
                    self._queue()
                self.assertEqual(self.Request.search_count([]), count)

    def test_expired_authorization_is_rejected_without_new_request(self):
        count = self.Request.search_count([])
        with self.assertRaises(ValidationError):
            self.Request._queue_for_people(self.person, self.devices, self.env.company, self.env.user,
                authorization_expires_at=fields.Datetime.now()-timedelta(seconds=1))
        self.assertEqual(self.Request.search_count([]), count)

    def test_capability_timeout_closes_session_without_creating_a_request(self):
        self.protocol_patch.stop()
        count = self.Request.search_count([])
        with patch('odoo.addons.access_control_api.models.access_resync.requests.Session') as session:
            session.return_value.__enter__.return_value.get.side_effect = requests.Timeout('QA timeout')
            with self.assertRaises(ValidationError):
                self._queue()
            session.return_value.__exit__.assert_called_once()
        self.assertEqual(self.Request.search_count([]), count)

    def test_destination_limit_counts_authorized_pairs_not_the_cartesian_product(self):
        other_site = self.env['access_control.site'].create({'name': 'Other recovery QA', 'code': 'OTHER-RECOVERY-QA'})
        partner = self.partner.copy({'name': 'Other recovery participant'})
        person = self.env['access_control.person'].create({
            'partner_id': partner.id, 'active': True, 'site_ids': [(6, 0, other_site.ids)]})
        devices = self.env['access_control.device'].create([
            {'name': 'LIMIT-%s-%s' % (site.id, n), 'device_serial': 'LIMIT-%s-%s' % (site.id, n), 'site_id': site.id}
            for site in (self.site, other_site) for n in range(16)])
        request = self.Request._queue_for_people(self.person | person, devices, self.env.company, self.env.user)
        self.assertEqual(len(request.target_ids), 32)
        self.assertTrue(all(t.device_id.site_id in t.person_id.site_ids for t in request.target_ids))
        extra = self.env['access_control.device'].create({
            'name': 'Over limit', 'device_serial': 'OVER-LIMIT', 'site_id': self.site.id})
        count = self.Request.search_count([])
        with self.assertRaises(ValidationError):
            self.Request._queue_for_people(self.person | person, devices | extra, self.env.company, self.env.user)
        self.assertEqual(self.Request.search_count([]), count)

    def test_confirmation_is_historical_evidence_after_later_suspension(self):
        request = self._queue(self.devices[0])
        target = request.target_ids
        target.state = 'confirmed'
        self.person.access_state = 'suspended'
        self.assertFalse(target._recovery_metadata(self.person, self.devices[0]))
        self.assertEqual(target.state, 'confirmed')

    def test_disabled_timezone_cannot_be_dispatched_even_if_its_intervals_did_not_change(self):
        timezone = self.env['access_control.timezone'].create({'name': 'Recovery custom timezone', 'timezone_id': 37})
        self.person.access_timezone_id = timezone
        request = self._queue(self.devices[0])
        self.person.access_timezone_id.active = False
        target = request.target_ids
        self.assertFalse(target._recovery_metadata(self.person, self.devices[0]))
        self.assertEqual(target.state, 'superseded')

    def test_delta_contains_full_recovery_only_for_the_selected_device(self):
        cursor = self.env['access_control.sync_change'].search([], order='id desc', limit=1).id
        request = self._queue(self.devices[1])
        self.assertFalse(self._delta(self.devices[0], cursor)['upserts'])
        rows = self._delta(self.devices[1], cursor)['upserts']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['recovery']['token'], request.target_ids.token)
        self.assertTrue(rows[0]['facePicB64'])
        self.assertEqual(len(rows[0]['recovery']['intervals']), 7)
        self.assertEqual(request.target_ids.state, 'sent')

    def test_expired_recovery_does_not_fall_back_to_an_ordinary_upsert(self):
        cursor = self.env['access_control.sync_change'].search([], order='id desc', limit=1).id
        request = self._queue(self.devices[0])
        request.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        self.assertFalse(self._delta(self.devices[0], cursor)['upserts'])
        self.assertEqual(request.target_ids.state, 'expired')

    def test_recovery_without_photo_is_explicitly_failed_and_never_clears_a_device_photo(self):
        self.person.with_context(skip_access_sync_queue=True).write({'face_pic_b64': False, 'face_image': False})
        self.partner.with_context(skip_access_sync_queue=True).image_1920 = False
        request = self._queue()
        self.assertEqual(set(request.target_ids.mapped('state')), {'failed'})
        self.assertFalse(self.env['access_control.sync_change'].search([('resync_target_id', 'in', request.target_ids.ids)]))

    def test_person_face_is_preserved_when_partner_has_no_image(self):
        self.partner.with_context(skip_access_sync_queue=True).image_1920 = False
        image = io.BytesIO()
        Image.new('RGB', (400, 400), (90, 130, 170)).save(image, format='JPEG')
        self.person.with_context(skip_access_sync_queue=True).write({'face_pic_b64': base64.b64encode(image.getvalue()).decode()})
        request = self._queue()
        self.assertEqual(set(request.target_ids.mapped('state')), {'queued'})
        self.assertTrue(self.person.face_pic_b64)

    def test_suspended_person_cannot_receive_enabled_recovery(self):
        self.person.access_state = 'suspended'
        request = self._queue()
        self.assertEqual(set(request.target_ids.mapped('state')), {'failed'})

    def _gateway_response(self, request, state, code='0'):
        return [{
            'token': target.token, 'device_serial': target.device_id.device_serial,
            'pin': str(target.global_user_id), 'state': state,
            'commands': [{'id': n, 'status': 'acked', 'ack_return': code} for n in range(1, 5)],
        } for target in request.target_ids]

    def test_gateway_confirmation_is_device_scoped_and_resources_close(self):
        request = self._queue()
        payload = self._gateway_response(request, 'confirmed')
        payload[1]['device_serial'] = 'WRONG'
        with patch('odoo.addons.access_control_api.models.access_resync.requests.Session') as session:
            response = session.return_value.__enter__.return_value.get.return_value.__enter__.return_value
            response.json.return_value = payload
            response.content = b'[]'
            request._status_payload(refresh=True)
            self.assertEqual(request.target_ids[0].state, 'confirmed')
            self.assertEqual(request.target_ids[1].state, 'queued')
            session.return_value.__enter__.return_value.get.return_value.__exit__.assert_called_once()
            session.return_value.__exit__.assert_called_once()

    def test_confirmation_requires_four_distinct_successful_command_acknowledgements(self):
        request = self._queue(self.devices[0])
        payload = self._gateway_response(request, 'confirmed', code='-629')
        with patch('odoo.addons.access_control_api.models.access_resync.requests.Session') as session:
            response = session.return_value.__enter__.return_value.get.return_value.__enter__.return_value
            response.content = b'[]'
            response.json.return_value = payload
            request._status_payload(refresh=True)
        self.assertEqual(request.target_ids.state, 'queued')

    def test_changed_photo_or_authorization_supersedes_pending_recovery(self):
        request = self._queue()
        self.person.access_state = 'suspended'
        with patch('odoo.addons.access_control_api.models.access_resync.requests.Session') as session:
            request._status_payload(refresh=True)
            session.assert_not_called()
        self.assertEqual(set(request.target_ids.mapped('state')), {'superseded'})

    def test_disabled_timezone_also_supersedes_status_without_querying_the_gateway(self):
        self.person.access_timezone_id = self.env['access_control.timezone'].create({'name': 'Status QA'})
        request = self._queue()
        self.person.access_timezone_id.active = False
        with patch('odoo.addons.access_control_api.models.access_resync.requests.Session') as session:
            request._status_payload(refresh=True)
            session.assert_not_called()
        self.assertEqual(set(request.target_ids.mapped('state')), {'superseded'})

    def test_malformed_command_ids_cannot_confirm_or_crash_status(self):
        request = self._queue(self.devices[0])
        for invalid in ([], True, 0, '1'):
            payload = self._gateway_response(request, 'confirmed')
            payload[0]['commands'][0]['id'] = invalid
            with patch('odoo.addons.access_control_api.models.access_resync.requests.Session') as session:
                response = session.return_value.__enter__.return_value.get.return_value.__enter__.return_value
                response.content = b'[]'
                response.json.return_value = payload
                self.assertEqual(request._status_payload(refresh=True)['state'], 'pending')

    def test_http_failure_or_old_gateway_never_reports_success(self):
        request = self._queue()
        with patch('odoo.addons.access_control_api.models.access_resync.requests.Session') as session:
            session.return_value.__enter__.return_value.get.side_effect = requests.Timeout('QA timeout')
            result = request._status_payload(refresh=True)
        self.assertEqual(result['state'], 'pending')
        self.assertNotIn('confirmed', request.target_ids.mapped('state'))

    def test_expiration_without_acknowledgement_is_not_confirmation(self):
        request = self._queue()
        request.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        with patch('odoo.addons.access_control_api.models.access_resync.requests.Session') as session:
            session.return_value.__enter__.return_value.get.side_effect = requests.Timeout('QA timeout')
            result = request._status_payload(refresh=True)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(set(request.target_ids.mapped('state')), {'expired'})
