# -*- coding: utf-8 -*-
import json
import logging
import time

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)


class AccessControlDeviceAuditRun(models.Model):
    _name = "access_control.device_audit_run"
    _description = "Auditoría de Inventario SpeedFace"
    _order = "started_at desc, id desc"

    name = fields.Char(required=True, default=lambda self: _("Auditoría SF"))
    device_id = fields.Many2one("access_control.device", required=True, index=True, ondelete="cascade")
    site_id = fields.Many2one("access_control.site", related="device_id.site_id", store=True, readonly=True)
    device_serial = fields.Char(related="device_id.device_serial", store=True, readonly=True)
    state = fields.Selection(
        [("draft", "Borrador"), ("running", "Ejecutando"), ("done", "Completada"), ("error", "Error")],
        default="draft",
        required=True,
        index=True,
    )
    started_at = fields.Datetime(default=fields.Datetime.now, required=True)
    completed_at = fields.Datetime(readonly=True)
    users_updated_at = fields.Char(string="Inventario usuarios ADMS", readonly=True)
    authorize_updated_at = fields.Char(string="Inventario horarios ADMS", readonly=True)
    expected_count = fields.Integer(readonly=True)
    real_count = fields.Integer(readonly=True)
    orphan_count = fields.Integer(readonly=True)
    missing_count = fields.Integer(readonly=True)
    drift_count = fields.Integer(readonly=True)
    timezone_drift_count = fields.Integer(readonly=True)
    error_message = fields.Text(readonly=True)
    raw_snapshot = fields.Text(readonly=True)
    line_ids = fields.One2many("access_control.device_audit_line", "run_id", string="Hallazgos")

    @api.model
    def run_for_devices(self, devices):
        runs = self.browse()
        for device in devices.exists():
            runs |= self._run_for_device(device)
        return runs

    @api.model
    def _run_for_device(self, device):
        device.ensure_one()
        if not device.active:
            raise UserError(_("Solo se pueden auditar SpeedFace activos."))
        run = self.create(
            {
                "name": _("Auditoría %(device)s %(date)s")
                % {"device": device.display_name, "date": fields.Datetime.to_string(fields.Datetime.now())},
                "device_id": device.id,
                "state": "running",
            }
        )
        try:
            snapshot = run._fetch_adms_inventory()
            run._compare_snapshot(snapshot)
        except Exception as error:
            run.write({"state": "error", "completed_at": fields.Datetime.now(), "error_message": str(error)})
            _logger.exception("access_device_audit failed device_id=%s serial=%s", device.id, device.device_serial)
            raise
        return run

    def _adms_headers(self):
        self.ensure_one()
        _base_url, token = self.device_id._get_adms_config()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer %s" % token
            headers["X-API-Token"] = token
        return headers

    def _adms_url(self, path):
        self.ensure_one()
        base_url, _token = self.device_id._get_adms_config()
        return "%s%s" % (base_url, path)

    def _fetch_adms_inventory(self):
        self.ensure_one()
        payload = {
            "deviceSerial": self.device_id.device_serial,
            "includeAuthorize": True,
            "priority": True,
        }
        try:
            post = requests.post(
                self._adms_url("/admin/devices/query-users"),
                json=payload,
                headers=self._adms_headers(),
                timeout=10,
            )
            post.raise_for_status()
        except requests.RequestException as error:
            raise UserError(_("No se pudo solicitar inventario a ADMS: %s") % error) from error

        ICP = self.env["ir.config_parameter"].sudo()
        attempts = max(1, int(ICP.get_param("access_control.audit_poll_attempts", default="5") or 5))
        delay = max(0.0, float(ICP.get_param("access_control.audit_poll_delay_seconds", default="1") or 1))
        last_error = None
        for attempt in range(attempts):
            if attempt and delay:
                time.sleep(delay)
            try:
                response = requests.get(
                    self._adms_url("/admin/users/synced"),
                    params={"sn": self.device_id.device_serial},
                    headers=self._adms_headers(),
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json() if response.content else {}
                if isinstance(data, dict) and (data.get("users") is not None or data.get("authorizations") is not None):
                    return data
            except (requests.RequestException, ValueError) as error:
                last_error = error
        if last_error:
            raise UserError(_("No se pudo leer inventario ADMS: %s") % last_error)
        raise UserError(_("ADMS no devolvió inventario sincronizado para el SF seleccionado."))

    def _expected_inventory(self):
        self.ensure_one()
        Person = self.env["access_control.person"].sudo()
        people = Person.search(
            [
                ("active", "=", True),
                ("global_user_id", "!=", False),
                ("site_ids", "in", [self.site_id.id]),
            ],
            order="global_user_id asc",
        )
        expected = {}
        for person in people:
            pin = str(int(person.global_user_id))
            expected[pin] = {
                "person": person,
                "pin": pin,
                "name": person.name or "",
                "group": 0 if person.access_state == "suspended" else 1,
                "disable": 0,
                "authorize_timezone_id": int(person.authorize_timezone_id or 1),
                "authorize_door_id": 1,
                "dev_id": 1,
            }
        return expected

    def _compare_snapshot(self, snapshot):
        self.ensure_one()
        expected = self._expected_inventory()
        real_users = {}
        for item in snapshot.get("users") or []:
            pin = self._pin(item.get("pin") or item.get("PIN"))
            if pin:
                real_users[pin] = item
        real_auth = {}
        for item in snapshot.get("authorizations") or []:
            pin = self._pin(item.get("pin") or item.get("PIN"))
            if pin:
                real_auth[pin] = item

        lines = []
        for pin, user in sorted(real_users.items(), key=lambda pair: int(pair[0]) if pair[0].isdigit() else 0):
            if pin not in expected:
                lines.append(self._line_vals("orphan", pin, actual=user, actual_auth=real_auth.get(pin)))

        for pin, exp in sorted(expected.items(), key=lambda pair: int(pair[0])):
            user = real_users.get(pin)
            auth = real_auth.get(pin) or {}
            if not user:
                lines.append(self._line_vals("missing", pin, expected=exp, person=exp["person"]))
                continue
            expected_name = self._clean_name(exp["name"])
            actual_name = self._clean_name(self._first_value(user, "name", "Name"))
            if expected_name != actual_name:
                lines.append(self._line_vals("name_drift", pin, expected=exp, actual=user, actual_auth=auth, person=exp["person"]))

            expected_group = int(exp["group"])
            actual_group = self._as_int(self._first_value(user, "group", "accessGroup"), default=0)
            expected_disable = int(exp["disable"])
            actual_disable = self._as_int(self._first_value(user, "disable", "disabled"), default=0)
            expected_door = int(exp["authorize_door_id"])
            actual_door = self._as_int(self._first_value(auth, "authorize_door_id", "authorizeDoorId", "door_id"), default=0)
            expected_dev = int(exp["dev_id"])
            actual_dev = self._as_int(self._first_value(auth, "dev_id", "authorizeDevId", "authorize_dev_id"), default=0)
            if (
                expected_group != actual_group
                or expected_disable != actual_disable
                or expected_door != actual_door
                or expected_dev != actual_dev
            ):
                lines.append(self._line_vals("access_drift", pin, expected=exp, actual=user, actual_auth=auth, person=exp["person"]))

            expected_tz = int(exp["authorize_timezone_id"])
            actual_tz = self._as_int(
                self._first_value(auth, "authorize_timezone_id", "authorizeTimezoneId", "authorize_timezoneid"),
                default=1,
            )
            if expected_tz != actual_tz:
                lines.append(self._line_vals("timezone_drift", pin, expected=exp, actual=user, actual_auth=auth, person=exp["person"]))

        self.line_ids.unlink()
        if lines:
            self.env["access_control.device_audit_line"].sudo().create(lines)
        self.write(
            {
                "state": "done",
                "completed_at": fields.Datetime.now(),
                "users_updated_at": snapshot.get("users_updated_at") or snapshot.get("updated_at") or False,
                "authorize_updated_at": snapshot.get("authorize_updated_at") or False,
                "expected_count": len(expected),
                "real_count": len(real_users),
                "orphan_count": len([line for line in lines if line["issue_type"] == "orphan"]),
                "missing_count": len([line for line in lines if line["issue_type"] == "missing"]),
                "timezone_drift_count": len([line for line in lines if line["issue_type"] == "timezone_drift"]),
                "drift_count": len([line for line in lines if line["issue_type"] in ("name_drift", "access_drift", "timezone_drift")]),
                "raw_snapshot": json.dumps(snapshot, ensure_ascii=True, default=str),
            }
        )

    def _line_vals(self, issue_type, pin, expected=None, actual=None, actual_auth=None, person=None):
        expected = expected or {}
        actual = actual or {}
        actual_auth = actual_auth or {}
        return {
            "run_id": self.id,
            "device_id": self.device_id.id,
            "site_id": self.site_id.id,
            "issue_type": issue_type,
            "global_user_id": int(pin) if str(pin).isdigit() else 0,
            "person_id": person.id if person else False,
            "expected_name": expected.get("name") or False,
            "actual_name": self._first_value(actual, "name", "Name") or False,
            "expected_timezone_id": expected.get("authorize_timezone_id") or False,
            "actual_timezone_id": self._as_int(
                self._first_value(actual_auth, "authorize_timezone_id", "authorizeTimezoneId", "authorize_timezoneid"),
                default=False,
            ),
            "expected_group": expected.get("group") if expected else False,
            "actual_group": self._as_int(self._first_value(actual, "group", "accessGroup"), default=False),
            "expected_disable": expected.get("disable") if expected else False,
            "actual_disable": self._as_int(self._first_value(actual, "disable", "disabled"), default=False),
            "raw_expected": json.dumps(expected, ensure_ascii=True, default=str) if expected else False,
            "raw_actual": json.dumps({"user": actual, "authorization": actual_auth}, ensure_ascii=True, default=str),
        }

    @api.model
    def _pin(self, value):
        text = str(value or "").strip()
        if not text:
            return False
        try:
            return str(int(text))
        except (TypeError, ValueError):
            return text

    @api.model
    def _as_int(self, value, default=0):
        if isinstance(value, bool):
            return 1 if value else 0
        try:
            text = str(value).strip().lower()
            if text in ("true", "yes", "y", "si", "sí"):
                return 1
            if text in ("false", "no", "n"):
                return 0
            return int(text)
        except (TypeError, ValueError):
            return default

    @api.model
    def _first_value(self, data, *keys):
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
        return None

    @api.model
    def _clean_name(self, value):
        return " ".join(str(value or "").strip().split())


class AccessControlDeviceAuditLine(models.Model):
    _name = "access_control.device_audit_line"
    _description = "Hallazgo de Auditoría SpeedFace"
    _order = "issue_type asc, global_user_id asc, id asc"

    run_id = fields.Many2one("access_control.device_audit_run", required=True, index=True, ondelete="cascade")
    device_id = fields.Many2one("access_control.device", required=True, index=True, ondelete="cascade")
    site_id = fields.Many2one("access_control.site", index=True, ondelete="set null")
    issue_type = fields.Selection(
        [
            ("orphan", "Huérfano en SF"),
            ("missing", "Faltante en SF"),
            ("name_drift", "Nombre distinto"),
            ("timezone_drift", "Horario distinto"),
            ("access_drift", "Grupo/disable distinto"),
        ],
        required=True,
        index=True,
    )
    state = fields.Selection([("open", "Abierto"), ("resolved", "Resuelto"), ("ignored", "Ignorado")], default="open", index=True)
    global_user_id = fields.Integer(string="PIN", index=True)
    person_id = fields.Many2one("access_control.person", index=True, ondelete="set null")
    expected_name = fields.Char()
    actual_name = fields.Char()
    expected_timezone_id = fields.Integer()
    actual_timezone_id = fields.Integer()
    expected_group = fields.Integer()
    actual_group = fields.Integer()
    expected_disable = fields.Integer()
    actual_disable = fields.Integer()
    raw_expected = fields.Text()
    raw_actual = fields.Text()

    def action_resync(self):
        Change = self.env["access_control.sync_change"].sudo()
        for line in self:
            if line.issue_type == "orphan" or not line.person_id:
                continue
            Change.with_context(access_sync_priority=True).queue_upsert_for_person(
                line.person_id,
                site_ids=line.site_id,
                reason="device_audit_resync",
                include_face_pic=bool(line.person_id.face_pic_b64),
                priority=True,
            )
            line.state = "resolved"
        return True

    def action_ignore(self):
        self.write({"state": "ignored"})
        return True

    def action_open_delete_orphan_wizard(self):
        self.ensure_one()
        if self.issue_type != "orphan":
            raise UserError(_("Solo los huérfanos se pueden borrar desde ADMS."))
        wizard = self.env["access_control.device_audit_delete_wizard"].create({"line_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("Confirmar borrado de huérfano"),
            "res_model": "access_control.device_audit_delete_wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }


class AccessControlDeviceAuditDeleteWizard(models.TransientModel):
    _name = "access_control.device_audit_delete_wizard"
    _description = "Confirmar borrado de huérfano ADMS"

    line_id = fields.Many2one("access_control.device_audit_line", required=True, ondelete="cascade")
    device_id = fields.Many2one(related="line_id.device_id", readonly=True)
    global_user_id = fields.Integer(related="line_id.global_user_id", readonly=True)
    confirmation = fields.Char(string="Confirmación")

    def action_confirm_delete(self):
        self.ensure_one()
        if self.confirmation != "BORRAR":
            raise ValidationError(_("Escribe BORRAR para confirmar la eliminación en ADMS."))
        line = self.line_id
        base_url, token = line.device_id._get_adms_config()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer %s" % token
            headers["X-API-Token"] = token
        try:
            response = requests.post(
                "%s/admin/users/delete" % base_url,
                json={
                    "pin": str(line.global_user_id),
                    "devices": [line.device_id.device_serial],
                    "priority": True,
                },
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise UserError(_("No se pudo borrar el huérfano en ADMS: %s") % error) from error
        line.state = "resolved"
        return {"type": "ir.actions.act_window_close"}
