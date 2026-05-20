# -*- coding: utf-8 -*-
import base64
import io
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError

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
        cls.Partner = cls.env["res.partner"].sudo()
        cls.Person = cls.env["access_control.person"].sudo()
        cls.Change = cls.env["access_control.sync_change"].sudo()
        cls.site = cls.Site.create({"name": "Centro", "code": "MX-CEN"})

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

    def test_bootstrap_helper_returns_full_snapshot(self):
        _, person = self._make_person(self._make_image_b64())
        result = self.controller._site_bootstrap_result(
            self.site,
            self.site.code,
            "DEV-001",
            3303,
            3303,
            reason="stale_cursor_bootstrap",
        )

        self.assertEqual(result["reason"], "stale_cursor_bootstrap")
        self.assertEqual(result["cursor"], 3303)
        self.assertEqual(result["nextCursor"], 3303)
        self.assertEqual(result["deviceSerial"], "DEV-001")
        self.assertEqual(len(result["upserts"]), 1)
        self.assertEqual(result["upserts"][0]["globalUserId"], person.global_user_id)
        self.assertIn("facePicB64", result["upserts"][0])

    def test_stale_cursor_reuses_client_cursor_when_queue_is_empty(self):
        self.assertEqual(self.controller._bootstrap_cursor_for_stale_state(3303, 0), 3303)
        self.assertEqual(self.controller._bootstrap_cursor_for_stale_state(3303, 120), 120)

    def test_suspended_person_uses_zero_access_group(self):
        _, person = self._make_person(self._make_image_b64())
        person.write({"access_state": "suspended"})
        payload = self.controller._person_sync_payload(person, include_face_pic=False, clear_face_pic=False)
        self.assertEqual(payload["accessGroup"], 0)

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
