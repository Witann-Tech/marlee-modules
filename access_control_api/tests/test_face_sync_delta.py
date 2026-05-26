# -*- coding: utf-8 -*-
import base64
import io
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError

from odoo.addons.access_control_api.controllers.main import AccessControlApi
from odoo.addons.access_control_api.models import res_partner as res_partner_module

try:
    from PIL import Image
except ImportError:  # pragma: no cover - depends on test runtime
    Image = None


class TestFaceSyncDelta(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = AccessControlApi()
        cls.Site = cls.env["access_control.site"].sudo()
        cls.Device = cls.env["access_control.device"].sudo()
        cls.Partner = cls.env["res.partner"].sudo()
        cls.Person = cls.env["access_control.person"].sudo()
        cls.Change = cls.env["access_control.sync_change"].sudo()
        cls.site = cls.Site.create({"name": "Centro", "code": "MX-CEN"})
        cls.device = cls.Device.create(
            {
                "name": "Puerta Test",
                "device_serial": "DEV-TEST-001",
                "site_id": cls.site.id,
            }
        )

    def setUp(self):
        super().setUp()
        self.Change.search([]).unlink()

    def _make_image_b64(self, size=(900, 900), color=(180, 40, 40)):
        if not Image:
            self.skipTest("Pillow no está disponible en runtime de pruebas.")
        image = Image.new("RGB", size, color)
        output = io.BytesIO()
        image.save(output, format="PNG")
        return base64.b64encode(output.getvalue()).decode()

    def _make_person(self, image_b64):
        partner = self.Partner.create(
            {
                "name": "Persona Test",
                "image_1920": image_b64,
            }
        )
        person = self.Person.create(
            {
                "partner_id": partner.id,
                "global_user_id": 100 + self.Person.search_count([]) + 1,
                "active": True,
                "site_ids": [(6, 0, [self.site.id])],
            }
        )
        return partner, person

    def test_create_with_valid_face_includes_facepicb64(self):
        partner, person = self._make_person(self._make_image_b64())
        change = self.Change.search([("person_id", "=", person.id)], order="id desc", limit=1)

        self.assertTrue(change.include_face_pic)
        self.assertFalse(change.clear_face_pic)

        payload = self.controller._person_sync_payload(person, include_face_pic=True, clear_face_pic=False)
        self.assertIn("facePicB64", payload)
        self.assertTrue(payload["facePicB64"])

        raw = base64.b64decode(payload["facePicB64"])
        self.assertLessEqual(len(raw), 500 * 1024)

        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (480, 640))

        self.assertEqual(partner.id, person.partner_id.id)

    def test_update_with_new_face_includes_new_facepicb64(self):
        partner, person = self._make_person(self._make_image_b64(color=(180, 40, 40)))
        initial_payload = self.controller._person_sync_payload(person, include_face_pic=True, clear_face_pic=False)

        partner.write({"image_1920": self._make_image_b64(color=(40, 40, 180))})
        person.invalidate_recordset(["face_pic_b64", "face_image"])
        change = self.Change.search([("person_id", "=", person.id)], order="id desc", limit=1)

        self.assertTrue(change.include_face_pic)
        self.assertFalse(change.clear_face_pic)

        new_payload = self.controller._person_sync_payload(person, include_face_pic=True, clear_face_pic=False)
        self.assertNotEqual(initial_payload["facePicB64"], new_payload["facePicB64"])

    def test_delete_face_sends_null(self):
        partner, person = self._make_person(self._make_image_b64())
        partner.write({"image_1920": False})
        person.invalidate_recordset(["face_pic_b64", "face_image"])
        change = self.Change.search([("person_id", "=", person.id)], order="id desc", limit=1)

        self.assertFalse(change.include_face_pic)
        self.assertTrue(change.clear_face_pic)

        payload = self.controller._person_sync_payload(person, include_face_pic=False, clear_face_pic=True)
        self.assertIn("facePicB64", payload)
        self.assertIsNone(payload["facePicB64"])

    def test_payload_omits_facepicb64_when_face_unchanged(self):
        _, person = self._make_person(self._make_image_b64())
        payload = self.controller._person_sync_payload(person, include_face_pic=False, clear_face_pic=False)
        self.assertNotIn("facePicB64", payload)

    def test_bootstrap_helper_paginates_and_respects_limit(self):
        _, person_1 = self._make_person(self._make_image_b64())
        _, person_2 = self._make_person(self._make_image_b64(color=(40, 40, 180)))

        first = self.controller._site_bootstrap_result(
            self.site,
            self.site.code,
            "DEV-001",
            0,
            1,
            reason="bootstrap",
        )

        self.assertEqual(first["reason"], "bootstrap")
        self.assertEqual(first["cursor"], 0)
        self.assertEqual(first["deviceSerial"], "DEV-001")
        self.assertEqual(len(first["upserts"]), 1)
        self.assertTrue(first["hasMore"])
        self.assertLess(first["nextCursor"], 0)
        self.assertEqual(first["upserts"][0]["globalUserId"], min(person_1.global_user_id, person_2.global_user_id))

        second = self.controller._site_bootstrap_result(
            self.site,
            self.site.code,
            "DEV-001",
            first["nextCursor"],
            1,
            reason="bootstrap",
        )

        self.assertEqual(len(second["upserts"]), 1)
        self.assertFalse(second["hasMore"])
        self.assertGreaterEqual(second["nextCursor"], 0)
        self.assertNotEqual(second["upserts"][0]["globalUserId"], first["upserts"][0]["globalUserId"])

    def test_bootstrap_cursor_encode_decode_roundtrip(self):
        encoded = self.controller._bootstrap_cursor_encode(3378, 40)
        self.assertLess(encoded, 0)
        self.assertEqual(self.controller._bootstrap_cursor_decode(encoded), (3378, 40))

    def test_bootstrap_without_biophoto_omits_facepicb64(self):
        _, person = self._make_person(self._make_image_b64())
        result = self.controller._site_bootstrap_result(
            self.site,
            self.site.code,
            "DEV-001",
            0,
            20,
            include_biophoto=False,
            reason="bootstrap",
        )

        self.assertEqual(len(result["upserts"]), 1)
        self.assertEqual(result["upserts"][0]["globalUserId"], person.global_user_id)
        self.assertNotIn("facePicB64", result["upserts"][0])

    def test_bootstrap_marks_person_last_sf_sync_without_queueing_change(self):
        _, person = self._make_person(self._make_image_b64())
        self.Change.search([]).unlink()

        self.controller._site_bootstrap_result(
            self.site,
            self.site.code,
            "DEV-001",
            0,
            20,
            include_biophoto=False,
            reason="bootstrap",
        )
        person.invalidate_recordset(["last_sf_sync_at"])

        self.assertTrue(person.last_sf_sync_at)
        self.assertFalse(self.Change.search([]))

    def test_biophoto_snapshot_only_returns_people_with_face_and_respects_limit(self):
        _, person_with_face_1 = self._make_person(self._make_image_b64())
        _, person_with_face_2 = self._make_person(self._make_image_b64(color=(40, 40, 180)))
        partner_without_face = self.Partner.create({"name": "Sin rostro"})
        self.Person.create(
            {
                "partner_id": partner_without_face.id,
                "global_user_id": 9993,
                "active": True,
                "site_ids": [(6, 0, [self.site.id])],
            }
        )

        first = self.controller._site_biophoto_result(
            self.site,
            self.site.code,
            "DEV-001",
            3388,
            1,
            reason="biophoto_bootstrap",
        )

        self.assertEqual(first["reason"], "biophoto_bootstrap")
        self.assertEqual(len(first["upserts"]), 1)
        self.assertTrue(first["hasMore"])
        self.assertLess(first["nextCursor"], 0)
        self.assertIn("facePicB64", first["upserts"][0])

        second = self.controller._site_biophoto_result(
            self.site,
            self.site.code,
            "DEV-001",
            first["nextCursor"],
            1,
            reason="biophoto",
        )

        self.assertEqual(len(second["upserts"]), 1)
        self.assertFalse(second["hasMore"])
        self.assertGreaterEqual(second["nextCursor"], 0)
        gids = {first["upserts"][0]["globalUserId"], second["upserts"][0]["globalUserId"]}
        self.assertEqual(gids, {person_with_face_1.global_user_id, person_with_face_2.global_user_id})

    def test_site_change_max_cursor_is_scoped_per_site(self):
        other_site = self.Site.create({"name": "Norte", "code": "MX-NTE"})
        _, person = self._make_person(self._make_image_b64())
        other_partner = self.Partner.create({"name": "Persona Norte"})
        other_person = self.Person.create(
            {
                "partner_id": other_partner.id,
                "global_user_id": 9990,
                "active": True,
                "site_ids": [(6, 0, [other_site.id])],
            }
        )

        self.Change.search([]).unlink()
        first_site_change = self.Change.create(
            {
                "site_id": self.site.id,
                "person_id": person.id,
                "global_user_id": person.global_user_id,
                "action": "upsert",
                "reason": "first_site",
            }
        )
        other_site_change = self.Change.create(
            {
                "site_id": other_site.id,
                "person_id": other_person.id,
                "global_user_id": other_person.global_user_id,
                "action": "upsert",
                "reason": "other_site",
            }
        )

        self.assertEqual(self.controller._site_change_max_cursor(self.site), first_site_change.id)
        self.assertEqual(self.controller._site_change_max_cursor(other_site), other_site_change.id)
        self.assertGreater(other_site_change.id, first_site_change.id)
        encoded = self.controller._bootstrap_cursor_encode(first_site_change.id, 20)
        self.assertEqual(self.controller._bootstrap_cursor_decode(encoded), (first_site_change.id, 20))

    def test_suspended_person_uses_zero_access_group(self):
        _, person = self._make_person(self._make_image_b64())
        person.write({"access_state": "suspended"})
        payload = self.controller._person_sync_payload(person, include_face_pic=False, clear_face_pic=False)
        self.assertEqual(payload["accessGroup"], 0)

    def test_priority_upsert_queue_marks_change_and_payload(self):
        _, person = self._make_person(self._make_image_b64())
        self.Change.search([]).unlink()

        self.Change.with_context(access_sync_priority=True).queue_upsert_for_person(
            person,
            reason="manual_resync",
            include_face_pic=False,
        )
        change = self.Change.search([("person_id", "=", person.id)], limit=1)
        payload = self.controller._person_sync_payload(
            person,
            include_face_pic=False,
            clear_face_pic=False,
            priority=change.priority,
        )

        self.assertTrue(change.priority)
        self.assertTrue(payload["priority"])

    def test_touch_device_telemetry_updates_heartbeat_and_sync(self):
        self.device.write(
            {
                "last_heartbeat_at": False,
                "last_sync_at": False,
                "last_error": "old",
            }
        )
        updated = self.controller._touch_device_telemetry(
            self.device,
            heartbeat=True,
            sync=True,
            error_marker=True,
        )
        self.device.invalidate_recordset(["last_heartbeat_at", "last_sync_at", "last_error"])

        self.assertTrue(updated)
        self.assertTrue(self.device.last_heartbeat_at)
        self.assertTrue(self.device.last_sync_at)
        self.assertFalse(self.device.last_error)

    def test_device_open_door_posts_to_adms_and_audits(self):
        self.env["ir.config_parameter"].sudo().set_param("ADMS_BASE_URL", "https://adms.example.test")
        self.env["ir.config_parameter"].sudo().set_param("INTERNAL_API_TOKEN", "secret-token")

        class MockResponse:
            content = b'{"ok": true, "queued": true}'

            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True, "queued": True}

        before_utc = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        with patch("odoo.addons.access_control_api.models.access_device.requests.post", return_value=MockResponse()) as post:
            result = self.device.open_door_via_adms(
                door_id=1,
                open_time_seconds=5,
                reason="subscription_access_log_button",
                operator_user=self.env.user,
            )
        after_utc = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=1)
        change = self.Change.search([("action", "=", "command"), ("device_id", "=", self.device.id)], limit=1)
        payload = json.loads(change.command_payload)

        self.assertTrue(result["ok"])
        self.assertTrue(result["queued"])
        post.assert_called_once()
        _, kwargs = post.call_args
        self.assertEqual(kwargs["json"]["deviceSerial"], self.device.device_serial)
        self.assertEqual(kwargs["json"]["doorId"], 1)
        self.assertEqual(kwargs["json"]["openTimeSeconds"], 5)
        self.assertEqual(kwargs["json"]["operatorUserId"], self.env.user.id)
        self.assertEqual(kwargs["json"]["reason"], "subscription_access_log_button")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(change.action, "command")
        self.assertEqual(change.command_type, "open_door")
        self.assertTrue(change.priority)
        self.assertEqual(payload["deviceSerial"], self.device.device_serial)
        self.assertTrue(payload["ok"])
        event = self.env["access_control.access_event"].search(
            [("event_id", "=", result["access_event_ref"])],
            limit=1,
        )
        self.assertTrue(event)
        event_payload = json.loads(event.raw_payload)
        self.assertEqual(event.device_id.id, self.device.id)
        self.assertEqual(event.site_id.id, self.site.id)
        self.assertEqual(event.device_serial, self.device.device_serial)
        self.assertEqual(event.modality, "manual_open_door")
        self.assertEqual(event.result, "allowed")
        self.assertGreaterEqual(event.occurred_at, before_utc)
        self.assertLessEqual(event.occurred_at, after_utc)
        self.assertEqual(event_payload["eventType"], "open_door")
        self.assertEqual(event_payload["operatorUserId"], self.env.user.id)
        self.assertEqual(event_payload["reason"], "subscription_access_log_button")

    def test_device_open_door_rejects_unqueued_adms_response(self):
        self.env["ir.config_parameter"].sudo().set_param("ADMS_BASE_URL", "https://adms.example.test")
        self.env["ir.config_parameter"].sudo().set_param("INTERNAL_API_TOKEN", "secret-token")

        class MockResponse:
            content = b'{"ok": true, "queued": false}'

            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True, "queued": False}

        with patch("odoo.addons.access_control_api.models.access_device.requests.post", return_value=MockResponse()):
            with self.assertRaises(UserError):
                self.device.open_door_via_adms(
                    door_id=1,
                    open_time_seconds=5,
                    reason="subscription_access_log_button",
                    operator_user=self.env.user,
                )

    def test_device_open_door_uses_local_adms_default_without_token(self):
        class MockResponse:
            content = b'{"ok": true, "queued": true}'

            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True, "queued": True}

        with patch("odoo.addons.access_control_api.models.access_device.requests.post", return_value=MockResponse()) as post:
            self.device.open_door_via_adms(
                door_id=1,
                open_time_seconds=5,
                reason="subscription_access_log_button",
                operator_user=self.env.user,
            )
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:18080/admin/devices/open-door")
        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")

    def test_register_access_event_updates_person_last_access(self):
        _, person = self._make_person(self._make_image_b64())
        occurred_at = fields.Datetime.now()

        person.register_access_event(
            occurred_at=occurred_at,
            result="allowed",
            site=self.site,
            device=self.device,
        )
        person.invalidate_recordset(
            ["last_access_at", "last_access_result", "last_access_site_id", "last_access_device_id"]
        )

        self.assertEqual(person.last_access_at, occurred_at)
        self.assertEqual(person.last_access_result, "allowed")
        self.assertEqual(person.last_access_site_id.id, self.site.id)
        self.assertEqual(person.last_access_device_id.id, self.device.id)

    def test_access_event_parser_uses_configured_source_timezone(self):
        self.env["ir.config_parameter"].sudo().set_param("access_control.event_source_timezone", "America/Mexico_City")
        received_at = datetime(2026, 5, 26, 2, 50, 0)

        parsed = self.controller._parse_access_event_datetime(
            "2026-05-25 20:50:00",
            env=self.env,
            received_at=received_at,
        )

        self.assertEqual(parsed, datetime(2026, 5, 26, 2, 50, 0))

    def test_access_event_parser_defaults_to_sf_source_timezone(self):
        received_at = datetime(2026, 5, 26, 2, 59, 0)

        parsed = self.controller._parse_access_event_datetime(
            "2026-05-25 23:59:00",
            env=self.env,
            received_at=received_at,
        )

        self.assertEqual(parsed, datetime(2026, 5, 26, 2, 59, 0))

    def test_access_event_parser_corrects_future_device_timezone_shift(self):
        self.env["ir.config_parameter"].sudo().set_param("access_control.event_source_timezone", "America/Mexico_City")
        received_at = datetime(2026, 5, 26, 2, 50, 0)

        parsed = self.controller._parse_access_event_datetime(
            "2026-05-25 23:50:00",
            env=self.env,
            received_at=received_at,
        )

        self.assertEqual(parsed, datetime(2026, 5, 26, 2, 50, 0))

    def test_partner_face_update_queues_upsert_with_face(self):
        partner, person = self._make_person(self._make_image_b64(color=(180, 40, 40)))
        self.Change.search([("person_id", "=", person.id)]).unlink()

        partner.write({"image_1920": self._make_image_b64(color=(40, 180, 40))})
        changes = self.Change.search([("person_id", "=", person.id)], order="id asc")

        self.assertTrue(changes)
        self.assertEqual(changes[-1].action, "upsert")
        self.assertTrue(changes[-1].include_face_pic)
        self.assertFalse(changes[-1].clear_face_pic)

        person.invalidate_recordset(["face_pic_b64", "face_image"])
        payload = self.controller._person_sync_payload(person, include_face_pic=True, clear_face_pic=False)
        self.assertIn("facePicB64", payload)
        self.assertTrue(payload["facePicB64"])

    def test_latest_delta_keeps_facepicb64_if_any_change_requires_it(self):
        _, person = self._make_person(self._make_image_b64())
        first = self.Change.create(
            {
                "site_id": self.site.id,
                "person_id": person.id,
                "global_user_id": person.global_user_id,
                "action": "upsert",
                "include_face_pic": True,
                "reason": "face_changed",
            }
        )
        second = self.Change.create(
            {
                "site_id": self.site.id,
                "person_id": person.id,
                "global_user_id": person.global_user_id,
                "action": "upsert",
                "include_face_pic": False,
                "clear_face_pic": False,
                "reason": "other_change",
            }
        )

        latest_by_gid = {}
        for ch in self.Change.browse([first.id, second.id]):
            gid = ch.global_user_id
            state = latest_by_gid.setdefault(
                gid,
                {"change": ch, "include_face_pic": False, "clear_face_pic": False},
            )
            state["change"] = ch
            if ch.action == "delete":
                state["include_face_pic"] = False
                state["clear_face_pic"] = False
                continue
            if ch.include_face_pic:
                state["include_face_pic"] = True
                state["clear_face_pic"] = False
            elif ch.clear_face_pic:
                state["include_face_pic"] = False
                state["clear_face_pic"] = True

        state = latest_by_gid[person.global_user_id]
        payload = self.controller._person_sync_payload(
            person,
            include_face_pic=bool(state["include_face_pic"]),
            clear_face_pic=bool(state["clear_face_pic"]),
        )
        self.assertIn("facePicB64", payload)
        self.assertTrue(payload["facePicB64"])

    def test_normalize_image_b64_accepts_bytes_without_b_prefix_corruption(self):
        original = self._make_image_b64()
        normalized = self.Partner._normalize_image_b64(original.encode())
        self.assertEqual(normalized, self.Partner._normalize_image_b64(original))

    def test_person_is_unique_per_partner(self):
        partner = self.Partner.create({"name": "Partner único"})
        self.Person.create(
            {
                "partner_id": partner.id,
                "global_user_id": 9991,
                "active": False,
            }
        )
        with self.assertRaises(ValidationError):
            self.Person.create(
                {
                    "partner_id": partner.id,
                    "global_user_id": 9992,
                    "active": False,
                }
            )

    def test_invalid_image_is_rejected(self):
        result = self.Partner._prepare_biometric_face_b64("esto-no-es-una-imagen", log_context="test_invalid")
        self.assertFalse(result)

    def test_too_large_processed_image_is_rejected(self):
        original_save = res_partner_module.Image.Image.save

        def oversized_save(image_self, output, format=None, quality=None, optimize=None, **kwargs):
            output.write(b"x" * (600 * 1024))

        with patch.object(res_partner_module.Image.Image, "save", oversized_save):
            result = self.Partner._prepare_biometric_face_b64(self._make_image_b64(), log_context="test_large")

        self.assertFalse(result)
        self.assertIsNotNone(original_save)
