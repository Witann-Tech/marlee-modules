# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AccessPerson(models.Model):
    _name = "access_control.person"
    _description = "Access Control Person (to sync to devices)"
    _rec_name = "partner_id"

    active = fields.Boolean(default=False, index=True)

    name = fields.Char(related='partner_id.name', store=True, readonly=True, index=True)

    site_id = fields.Many2one("access_control.site", ondelete="set null", index=True)

    # Stable external reference (e.g., membership number / ERP id)
    external_ref = fields.Char(index=True)

    # Critical: F18 sequential user id (1..500) controlled by Odoo per site
    f18_user_id = fields.Integer(string="F18 User ID", index=True)

    # Legacy / optional (may be removed later in favor of credential model)
    pin = fields.Char(string="PIN") 
    partner_id = fields.Many2one("res.partner", string="Partner", required=True, index=True)

    note = fields.Char()


    @api.onchange("partner_id")
    def _onchange_partner_id_set_external_ref(self):
        for rec in self:
            if rec.partner_id and not rec.external_ref:
                rec.external_ref = rec.partner_id.ref


    _sql_constraints = [
        ("uniq_site_f18_user_id", "unique(site_id, f18_user_id)", "F18 User ID must be unique per Site."),
        ("check_f18_user_id_range", "CHECK(f18_user_id IS NULL OR (f18_user_id >= 1 AND f18_user_id <= 500))", "F18 User ID must be between 1 and 500."),
    ]

    @api.constrains("active", "f18_user_id")
    def _check_active_requires_f18_user_id(self):
        for rec in self:
            if rec.active and rec.f18_user_id is None:
                # We keep this as a soft requirement at model level; endpoints may enforce strictly too.
                # If you prefer to allow active w/o f18_user_id in UI, comment this out.
                raise ValidationError("Active people must have an F18 User ID (1..500).")


    def action_assign_f18_user_id(self):
        """Assign the lowest available F18 User ID (1..500) within the selected site."""
        for rec in self:
            if not rec.site_id:
                raise ValidationError("Please set a Site before assigning an F18 User ID.")
            if rec.f18_user_id:
                continue
            # Compute used IDs for this site
            self.env.cr.execute(
                """
                SELECT f18_user_id
                  FROM access_control_person
                 WHERE site_id = %s
                   AND f18_user_id IS NOT NULL
                """,
                (rec.site_id.id,),
            )
            used = {row[0] for row in self.env.cr.fetchall() if row and row[0]}
            chosen = None
            for i in range(1, 501):
                if i not in used:
                    chosen = i
                    break
            if not chosen:
                raise ValidationError("No available F18 User IDs (1..500) for this Site.")
            rec.f18_user_id = chosen
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
            if not rec.site_id:
                raise ValidationError("Please set a Site before activating this person.")
            if not rec.f18_user_id:
                raise ValidationError("Please assign an F18 User ID (1..500) before activating this person.")
            rec.active = True
            # Nudge the worker to sync
            rec.site_id.force_sync = True
        return self._notify("Activated", "Person activated and marked for sync.")

    def action_deactivate(self):
        for rec in self:
            if not rec.active:
                continue
            rec.active = False
            if rec.site_id:
                rec.site_id.force_sync = True
        return self._notify("Deactivated", "Person deactivated and marked for sync.", typ="warning")

