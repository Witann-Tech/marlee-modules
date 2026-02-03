# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AccessPerson(models.Model):
    _name = "access_control.person"
    _description = "Access Control Person (to sync to devices)"
    _rec_name = "name"

    active = fields.Boolean(default=True, index=True)

    name = fields.Char(required=True, index=True)

    site_id = fields.Many2one("access_control.site", ondelete="set null", index=True)

    # Stable external reference (e.g., membership number / ERP id)
    external_ref = fields.Char(index=True)

    # Critical: F18 sequential user id (1..500) controlled by Odoo per site
    f18_user_id = fields.Integer(string="F18 User ID", index=True)

    # Legacy / optional (may be removed later in favor of credential model)
    pin = fields.Char(string="PIN")

    user_id = fields.Many2one("res.users", string="User")
    partner_id = fields.Many2one("res.partner", string="Partner")

    note = fields.Char()

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
