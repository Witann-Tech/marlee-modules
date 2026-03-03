# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AccessPerson(models.Model):
    _name = "access_control.person"
    _description = "Access Control Person (to sync to devices)"
    _rec_name = "partner_id"

    active = fields.Boolean(default=False, index=True)

    name = fields.Char(related="partner_id.name", store=True, readonly=True, index=True)

    site_ids = fields.Many2many(
        "access_control.site",
        "access_control_person_site_rel",
        "person_id",
        "site_id",
        string="Sites",
    )

    # Stable external reference (e.g., membership number / ERP id)
    external_ref = fields.Char(index=True)

    # Global sequential user id used by SpeedFace devices (1..10000)
    global_user_id = fields.Integer(string="Global User ID", index=True)

    partner_id = fields.Many2one("res.partner", string="Partner", required=True, index=True)
    credential_ids = fields.One2many("access_control.credential", "person_id", string="Credentials")

    note = fields.Char()

    @api.onchange("partner_id")
    def _onchange_partner_id_set_external_ref(self):
        for rec in self:
            if rec.partner_id and not rec.external_ref:
                rec.external_ref = rec.partner_id.ref

    _sql_constraints = [
        ("uniq_global_user_id", "unique(global_user_id)", "Global User ID must be unique."),
        (
            "check_global_user_id_range",
            "CHECK(global_user_id IS NULL OR (global_user_id >= 1 AND global_user_id <= 10000))",
            "Global User ID must be between 1 and 10000.",
        ),
    ]

    @api.constrains("active", "global_user_id", "site_ids")
    def _check_active_requirements(self):
        for rec in self:
            if rec.active and rec.global_user_id is None:
                raise ValidationError("Active people must have a Global User ID (1..10000).")
            if rec.active and not rec.site_ids:
                raise ValidationError("Active people must be assigned to at least one Site.")

    def action_assign_global_user_id(self):
        """Assign the lowest available Global User ID (1..10000)."""
        for rec in self:
            if rec.global_user_id:
                continue
            self.env.cr.execute(
                """
                SELECT global_user_id
                  FROM access_control_person
                 WHERE global_user_id IS NOT NULL
                """
            )
            used = {row[0] for row in self.env.cr.fetchall() if row and row[0]}
            chosen = None
            for i in range(1, 10001):
                if i not in used:
                    chosen = i
                    break
            if not chosen:
                raise ValidationError("No available Global User IDs (1..10000).")
            rec.global_user_id = chosen
        return True

    def _notify(self, title, message, typ="success"):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": typ,
                "sticky": False,
            },
        }

    def action_activate(self):
        for rec in self:
            if rec.active:
                continue
            if not rec.site_ids:
                raise ValidationError("Please assign at least one Site before activating this person.")
            if not rec.global_user_id:
                raise ValidationError("Please assign a Global User ID (1..10000) before activating this person.")
            rec.active = True
            rec.site_ids.write({"force_sync": True})
        return self._notify("Activated", "Person activated and marked for sync.")

    def action_deactivate(self):
        for rec in self:
            if not rec.active:
                continue
            rec.active = False
            if rec.site_ids:
                rec.site_ids.write({"force_sync": True})
        return self._notify("Deactivated", "Person deactivated and marked for sync.", typ="warning")
