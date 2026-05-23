# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api


_logger = logging.getLogger(__name__)


class AccessSyncChange(models.Model):
    _name = "access_control.sync_change"
    _description = "Cambio de Sincronización de Acceso"
    _order = "id asc"

    site_id = fields.Many2one("access_control.site", required=True, index=True, ondelete="cascade")
    person_id = fields.Many2one("access_control.person", index=True, ondelete="set null")
    global_user_id = fields.Integer(required=True, index=True)
    action = fields.Selection(
        [("upsert", "Alta/Actualización"), ("delete", "Eliminación")],
        required=True,
        index=True,
    )
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
