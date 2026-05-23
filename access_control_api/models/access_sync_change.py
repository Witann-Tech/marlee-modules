# -*- coding: utf-8 -*-
import json
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class AccessSyncChange(models.Model):
    _name = "access_control.sync_change"
    _description = "Cambio de Sincronización de Acceso"
    _order = "id asc"

    site_id = fields.Many2one("access_control.site", required=True, index=True, ondelete="cascade")
    person_id = fields.Many2one("access_control.person", index=True, ondelete="set null")
    global_user_id = fields.Integer(required=True, index=True)
    action = fields.Selection(
        [("upsert", "Alta/Actualización"), ("delete", "Eliminación"), ("command", "Comando")],
        required=True,
        index=True,
    )
    device_id = fields.Many2one("access_control.device", index=True, ondelete="set null")
    command_type = fields.Selection([("open_door", "Abrir puerta")], index=True)
    command_payload = fields.Text()
    command_state = fields.Selection(
        [("pending", "Pendiente"), ("sent", "Enviado")],
        default="pending",
        index=True,
    )
    command_delivered_at = fields.Datetime()
    include_face_pic = fields.Boolean(default=False)
    clear_face_pic = fields.Boolean(default=False)
    priority = fields.Boolean(default=False, index=True)
    reason = fields.Char()

    @api.model
    def _to_site_ids(self, site_ids):
        if not site_ids:
            return []
        if hasattr(site_ids, "ids"):
            return site_ids.ids
        if isinstance(site_ids, int):
            return [site_ids]
        return [int(x) for x in site_ids if x]

    @api.model
    def queue_upsert_for_person(
        self,
        person,
        site_ids=None,
        reason="person_update",
        include_face_pic=False,
        clear_face_pic=False,
        priority=None,
    ):
        if not person or not person.global_user_id:
            return False
        resolved_site_ids = self._to_site_ids(site_ids) or person.site_ids.ids
        if not resolved_site_ids:
            return False
        priority = bool(self.env.context.get("access_sync_priority")) if priority is None else bool(priority)
        vals_list = []
        for site_id in resolved_site_ids:
            vals_list.append(
                {
                    "site_id": site_id,
                    "person_id": person.id,
                    "global_user_id": person.global_user_id,
                    "action": "upsert",
                    "include_face_pic": bool(include_face_pic),
                    "clear_face_pic": bool(clear_face_pic),
                    "priority": priority,
                    "reason": reason,
                }
            )
        self.sudo().create(vals_list)
        _logger.info(
            "queue_upsert person_id=%s pin=%s sites=%s include_face_pic=%s clear_face_pic=%s priority=%s reason=%s",
            person.id,
            person.global_user_id,
            resolved_site_ids,
            bool(include_face_pic),
            bool(clear_face_pic),
            priority,
            reason,
        )
        return True

    @api.model
    def queue_open_door_command(
        self,
        device,
        door_id=1,
        open_time_seconds=5,
        reason="manual_open_door",
        operator_user=None,
        priority=True,
    ):
        if not device or not device.exists() or not device.active:
            raise UserError("El dispositivo seleccionado no existe o está inactivo.")
        if not device.device_serial:
            raise UserError("El dispositivo no tiene serial configurado.")
        if not device.site_id:
            raise UserError("El dispositivo no tiene sitio configurado.")
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
        priority = True if priority is None else bool(priority)
        payload = {
            "deviceSerial": device.device_serial,
            "doorId": door_id,
            "openTimeSeconds": open_time_seconds,
            "operatorUserId": operator_user.id,
            "reason": str(reason or "manual_open_door").strip(),
            "priority": priority,
        }
        change = self.sudo().create(
            {
                "site_id": device.site_id.id,
                "device_id": device.id,
                "global_user_id": 0,
                "action": "command",
                "command_type": "open_door",
                "command_payload": json.dumps(payload, ensure_ascii=True, default=str),
                "command_state": "pending",
                "priority": priority,
                "reason": payload["reason"],
            }
        )
        _logger.info(
            "queue_command type=open_door change_id=%s device_id=%s serial=%s priority=%s reason=%s",
            change.id,
            device.id,
            device.device_serial,
            priority,
            payload["reason"],
        )
        return {
            "ok": True,
            "change_id": change.id,
            "device_id": device.id,
            "device_name": device.display_name,
            "device_serial": device.device_serial,
            "door_id": door_id,
            "open_time_seconds": open_time_seconds,
            "priority": priority,
        }

    @api.model
    def queue_delete(self, global_user_id, site_ids, person=None, reason="person_update", priority=None):
        if not global_user_id:
            return False
        resolved_site_ids = self._to_site_ids(site_ids)
        if not resolved_site_ids:
            return False
        priority = bool(self.env.context.get("access_sync_priority")) if priority is None else bool(priority)
        vals_list = []
        for site_id in resolved_site_ids:
            vals_list.append(
                {
                    "site_id": site_id,
                    "person_id": person.id if person else False,
                    "global_user_id": int(global_user_id),
                    "action": "delete",
                    "priority": priority,
                    "reason": reason,
                }
            )
        self.sudo().create(vals_list)
        _logger.info(
            "queue_delete person_id=%s pin=%s sites=%s priority=%s reason=%s",
            person.id if person else None,
            int(global_user_id),
            resolved_site_ids,
            priority,
            reason,
        )
        return True
