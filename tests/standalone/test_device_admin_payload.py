"""Exercise the actual payload builder without an Odoo server."""

import ast
import base64
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]


class DeviceAdminPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / 'access_control_api/controllers/main.py').read_text())
        controller = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        method = next(node for node in controller.body if isinstance(node, ast.FunctionDef)
                      and node.name == '_person_sync_payload')
        namespace = {'base64': base64, '_logger': logging.getLogger(__name__)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<payload>', 'exec'), namespace)
        cls.payload = staticmethod(namespace['_person_sync_payload'])

    def setUp(self):
        self.person = SimpleNamespace(global_user_id=42, id=7, name='Admin', active=False,
                                      access_state='suspended', authorize_timezone_id=3)
        self.face = base64.b64encode(b'test-face').decode()
        self.controller = SimpleNamespace(_person_face_pic_b64=lambda person: self.face)
        self.selected = SimpleNamespace(_local_admin_people=lambda: [self.person])
        self.other = SimpleNamespace(_local_admin_people=lambda: [])

    def test_admin_has_face_and_general_access_only_on_selected_device(self):
        payload = self.payload(self.controller, self.person, device=self.selected, priority=True)
        self.assertEqual(payload['privilege'], 14)
        self.assertTrue(payload['active'])
        self.assertEqual(payload['accessGroup'], 1)
        self.assertEqual(payload['authorizeTimezoneId'], 1)
        self.assertEqual(payload['authorize_timezone_id'], 1)
        self.assertEqual(payload['facePicB64'], self.face)
        self.assertTrue(payload['priority'])
        for device in (self.other, None):
            payload = self.payload(self.controller, self.person, device=device)
            self.assertEqual(payload['privilege'], 0)
            self.assertFalse(payload['active'])
            self.assertEqual(payload['accessGroup'], 0)
            self.assertEqual(payload['authorizeTimezoneId'], 3)

    def test_removal_restores_personal_authorization(self):
        self.person.active = True
        self.person.access_state = 'enabled'
        self.selected._local_admin_people = lambda: []
        payload = self.payload(self.controller, self.person, device=self.selected)
        self.assertEqual(payload['privilege'], 0)
        self.assertTrue(payload['active'])
        self.assertEqual(payload['authorizeTimezoneId'], 3)


if __name__ == '__main__':
    unittest.main()
