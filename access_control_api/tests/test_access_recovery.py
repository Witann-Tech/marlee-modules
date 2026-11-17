import base64
import io
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import requests
from PIL import Image

from odoo import fields
from odoo.tests.common import TransactionCase

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
