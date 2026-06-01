# -*- coding: utf-8 -*-
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import requests

from odoo import _, api, models, fields
from odoo.exceptions import UserError
from odoo.tools import config as odoo_config


_logger = logging.getLogger(__name__)


class AccessControlDevice(models.Model):
    _name = "access_control.device"
    _description = "Dispositivo de Control de Acceso (SpeedFace)"
    _rec_name = "name"

    active = fields.Boolean(default=True)

    name = fields.Char(required=True)
    device_serial = fields.Char(required=True, index=True)

    site_id = fields.Many2one("access_control.site", required=True, ondelete="cascade")

    user_capacity = fields.Integer(string="Capacidad de usuarios", default=10000)

    # Telemetría (actualizada por middleware/ADMS)
    last_heartbeat_at = fields.Datetime(string="Último heartbeat", readonly=True)
    last_sync_at = fields.Datetime(string="Última sincronización", readonly=True)
    last_error = fields.Text(string="Último error", readonly=True)

    _device_serial_uniq = models.Constraint(
        "unique(device_serial)",
        "El serial del dispositivo debe ser único.",
    )
    _user_capacity_positive = models.Constraint(
        "CHECK(user_capacity IS NULL OR user_capacity > 0)",
        "La capacidad de usuarios debe ser mayor a cero.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda rec: rec.active)._queue_active_timezones_for_device_sites("device_create")
        return records

    def write(self, vals):
        before = {rec.id: (rec.active, rec.site_id.id) for rec in self}
        res = super().write(vals)
        if {"active", "site_id"}.intersection(vals):
            to_sync = self.filtered(
                lambda rec: rec.active and before.get(rec.id) != (rec.active, rec.site_id.id)
            )
            if to_sync:
                to_sync._queue_active_timezones_for_device_sites("device_write")
        return res

    def _queue_active_timezones_for_device_sites(self, reason):
        site_ids = sorted(set(self.filtered(lambda rec: rec.active and rec.site_id).mapped("site_id").ids))
        if not site_ids or "access_control.timezone" not in self.env.registry:
            return False
        return self.env["access_control.timezone"].sudo().queue_active_timezones_for_sites(site_ids=site_ids, reason=reason)

    def action_run_inventory_audit(self):
        runs = self.env["access_control.device_audit_run"].sudo().run_for_devices(self)
        action = {
            "type": "ir.actions.act_window",
            "name": "Auditorías SF",
            "res_model": "access_control.device_audit_run",
            "view_mode": "list,form",
            "domain": [("id", "in", runs.ids)],
        }
        if len(runs) == 1:
            action.update({"view_mode": "form", "res_id": runs.id})
        return action

    def action_enqueue_clean_resync(self):
        devices = self.exists()
        inactive = devices.filtered(lambda rec: not rec.active)
        if inactive:
            raise UserError(_("Solo se pueden inicializar/re-sincronizar SpeedFace activos."))
        site_ids = sorted(set(devices.filtered(lambda rec: rec.site_id).mapped("site_id").ids))
        if not site_ids:
            raise UserError(_("Selecciona al menos un SpeedFace con sitio configurado."))

        Change = self.env["access_control.sync_change"].sudo()
        Person = self.env["access_control.person"].sudo()
        timezone_count = 0
        if "access_control.timezone" in self.env.registry:
            last_change_id = Change.search([], order="id desc", limit=1).id or 0
            self.env["access_control.timezone"].sudo().queue_active_timezones_for_sites(
                site_ids=site_ids,
                reason="device_clean_resync_timezones",
            )
            timezone_count = Change.search_count(
                [
                    ("id", ">", last_change_id),
                    ("command_type", "=", "timezone_upsert"),
                    ("reason", "=", "device_clean_resync_timezones"),
                ]
            )

        user_count = 0
        for site_id in site_ids:
            people = Person.search(
                [
                    ("active", "=", True),
                    ("global_user_id", "!=", False),
                    ("site_ids", "in", [site_id]),
                ],
                order="global_user_id asc",
            )
            for person in people:
                if Change.with_context(access_sync_priority=True).queue_upsert_for_person(
                    person,
                    site_ids=[site_id],
                    reason="device_clean_resync_user",
                    include_face_pic=bool(person.face_pic_b64 or person.face_image or person.partner_id.image_1920),
                    priority=True,
                ):
                    user_count += 1

        _logger.info(
            "access_device clean_resync queued device_ids=%s site_ids=%s timezone_changes=%s user_changes=%s",
            devices.ids,
            site_ids,
            timezone_count,
            user_count,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Re-sincronización SF encolada"),
                "message": _(
                    "Se encolaron %(timezones)s comando(s) de horario y %(users)s usuario(s) como prioridad. "
                    "ADMS puede recogerlos con su cursor actual, sin reiniciar desde token 0."
                )
                % {"timezones": timezone_count, "users": user_count},
                "type": "success",
                "sticky": False,
            },
        }

    def _get_adms_config(self):
        ICP = self.env["ir.config_parameter"].sudo()
        base_url = (
            ICP.get_param("adms.base_url")
            or ICP.get_param("ADMS_BASE_URL")
            or ICP.get_param("access_control.adms_base_url")
            or os.environ.get("ADMS_BASE_URL")
            or os.environ.get("ACCESS_CONTROL_ADMS_BASE_URL")
            or odoo_config.get("adms_base_url")
            or odoo_config.get("ADMS_BASE_URL")
            or odoo_config.get("access_control_adms_base_url")
            or odoo_config.get("access_control.adms_base_url")
        )
        token = (
            ICP.get_param("adms.internal_api_token")
            or ICP.get_param("INTERNAL_API_TOKEN")
            or ICP.get_param("access_control.internal_api_token")
            or os.environ.get("INTERNAL_API_TOKEN")
            or os.environ.get("ADMS_INTERNAL_API_TOKEN")
            or os.environ.get("ACCESS_CONTROL_INTERNAL_API_TOKEN")
            or odoo_config.get("internal_api_token")
            or odoo_config.get("INTERNAL_API_TOKEN")
            or odoo_config.get("adms_internal_api_token")
            or odoo_config.get("access_control_internal_api_token")
            or odoo_config.get("access_control.internal_api_token")
        )
        return (base_url or "http://127.0.0.1:18080").strip().rstrip("/"), (token or "").strip()

    def _audit_open_door_request(self, payload, response_data=None, ok=False):
        self.ensure_one()
        try:
            audit_payload = dict(payload or {})
            audit_payload["ok"] = bool(ok)
            if response_data is not None:
                audit_payload["admsResponse"] = response_data
            self.env["access_control.sync_change"].sudo().create(
                {
                    "site_id": self.site_id.id,
                    "device_id": self.id,
                    "global_user_id": 0,
                    "action": "command",
                    "command_type": "open_door",
                    "command_payload": json.dumps(audit_payload, ensure_ascii=True, default=str),
                    "priority": True,
                    "reason": audit_payload.get("reason") or "subscription_access_log_button",
                }
            )
        except Exception:
            _logger.exception("access_device open_door audit failed device_id=%s", self.id)

    def _log_open_door_access_event(self, payload, response_data=None, operator_user=None):
        self.ensure_one()
        occurred_at = datetime.now(timezone.utc).replace(tzinfo=None)
        raw_payload = dict(payload or {})
        raw_payload.update(
            {
                "eventType": "open_door",
                "source": "odoo_pos",
                "operatorUserId": operator_user.id if operator_user else self.env.user.id,
                "operatorUserName": operator_user.display_name if operator_user else self.env.user.display_name,
            }
        )
        if response_data is not None:
            raw_payload["admsResponse"] = response_data
        event = self.env["access_control.access_event"].sudo().create(
            {
                "event_id": "open_door:%s:%s" % (self.device_serial, uuid.uuid4().hex),
                "site_id": self.site_id.id if self.site_id else False,
                "device_id": self.id,
                "device_serial": self.device_serial,
                "global_user_id": 0,
                "modality": "manual_open_door",
                "result": "allowed",
                "occurred_at": occurred_at,
                "raw_payload": json.dumps(raw_payload, ensure_ascii=True, default=str),
            }
        )
        _logger.info(
            "access_device open_door access_event event_id=%s device_id=%s serial=%s user_id=%s",
            event.event_id,
            self.id,
            self.device_serial,
            raw_payload["operatorUserId"],
        )
        return event

    def open_door_via_adms(self, door_id=1, open_time_seconds=5, reason="manual_open_door", operator_user=None):
        self.ensure_one()
        if not self.active:
            raise UserError("El dispositivo seleccionado está inactivo.")
        if not self.device_serial:
            raise UserError("El dispositivo no tiene serial configurado.")

        base_url, token = self._get_adms_config()
        if not base_url:
            raise UserError("Configura ADMS_BASE_URL antes de abrir puertas.")

        try:
            door_id = int(door_id or 1)
        except (TypeError, ValueError):
            door_id = 1
        try:
            open_time_seconds = int(open_time_seconds or 5)
        except (TypeError, ValueError):
            open_time_seconds = 5
        door_id = max(1, door_id)
        open_time_seconds = min(max(1, open_time_seconds), 60)
        operator_user = operator_user or self.env.user
        payload = {
            "deviceSerial": self.device_serial,
            "doorId": door_id,
            "openTimeSeconds": open_time_seconds,
            "operatorUserId": operator_user.id,
            "reason": str(reason or "manual_open_door").strip(),
        }

        url = "%s/admin/devices/open-door" % base_url
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer %s" % token
            headers["X-API-Token"] = token
        response_data = {}
        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=8,
            )
            response.raise_for_status()
            response_data = response.json() if response.content else {}
        except requests.RequestException as error:
            self._audit_open_door_request(payload, response_data={"error": str(error)}, ok=False)
            _logger.warning(
                "access_device open_door request failed device_id=%s serial=%s error=%s",
                self.id,
                self.device_serial,
                error,
            )
            raise UserError("No se pudo enviar el comando de apertura a ADMS.") from error
        except ValueError as error:
            self._audit_open_door_request(payload, response_data={"error": "invalid_json"}, ok=False)
            _logger.warning(
                "access_device open_door invalid_json device_id=%s serial=%s error=%s",
                self.id,
                self.device_serial,
                error,
            )
            raise UserError("ADMS respondió con un formato inválido.") from error

        if not isinstance(response_data, dict) or response_data.get("ok") is not True or response_data.get("queued") is not True:
            self._audit_open_door_request(payload, response_data=response_data, ok=False)
            raise UserError("ADMS no confirmó el encolado del comando de apertura.")

        self._audit_open_door_request(payload, response_data=response_data, ok=True)
        event = self._log_open_door_access_event(payload, response_data=response_data, operator_user=operator_user)
        _logger.info(
            "access_device open_door queued device_id=%s serial=%s user_id=%s door_id=%s open_time=%s",
            self.id,
            self.device_serial,
            operator_user.id,
            door_id,
            open_time_seconds,
        )
        return {
            "ok": True,
            "queued": True,
            "device_id": self.id,
            "device_name": self.display_name,
            "device_serial": self.device_serial,
            "door_id": door_id,
            "open_time_seconds": open_time_seconds,
            "access_event_id": event.id,
            "access_event_ref": event.event_id,
        }
