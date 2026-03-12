# -*- coding: utf-8 -*-
from odoo import models, fields, api


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
    def queue_upsert_for_person(self, person, site_ids=None, reason="person_update"):
        if not person or not person.global_user_id:
            return False
        resolved_site_ids = self._to_site_ids(site_ids) or person.site_ids.ids
        if not resolved_site_ids:
            return False
        vals_list = []
        for site_id in resolved_site_ids:
            vals_list.append(
                {
                    "site_id": site_id,
                    "person_id": person.id,
                    "global_user_id": person.global_user_id,
                    "action": "upsert",
                    "reason": reason,
                }
            )
        self.sudo().create(vals_list)
        return True

    @api.model
    def queue_delete(self, global_user_id, site_ids, person=None, reason="person_update"):
        if not global_user_id:
            return False
        resolved_site_ids = self._to_site_ids(site_ids)
        if not resolved_site_ids:
            return False
        vals_list = []
        for site_id in resolved_site_ids:
            vals_list.append(
                {
                    "site_id": site_id,
                    "person_id": person.id if person else False,
                    "global_user_id": int(global_user_id),
                    "action": "delete",
                    "reason": reason,
                }
            )
        self.sudo().create(vals_list)
        return True
