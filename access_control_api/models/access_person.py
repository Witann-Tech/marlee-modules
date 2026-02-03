# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AccessPerson(models.Model):
    _name = "access_control.person"
    _description = "Access Control Person (to sync to devices)"
    _rec_name = "name"

    active = fields.Boolean(default=True)

    name = fields.Char(required=True, index=True)

    # Stable external reference (optional)
    external_ref = fields.Char(index=True)

    # F18 requires a sequential user id (1..500). This is the authority for the device enrollNumber/userId.
    f18_user_id = fields.Integer(string="F18 User ID", index=True)

    # Optional PIN (if allowed)
    pin = fields.Char()

    # Optional references to link with your real data
    user_id = fields.Many2one("res.users", string="User")
    partner_id = fields.Many2one("res.partner", string="Partner")

    note = fields.Char()

    _sql_constraints = [
        ("access_control_person_f18_user_id_uniq", "unique(f18_user_id)", "F18 User ID must be unique."),
    ]

    @api.constrains("f18_user_id")
    def _check_f18_user_id_range(self):
        for rec in self:
            if rec.f18_user_id is None:
                continue
            if rec.f18_user_id < 1 or rec.f18_user_id > 500:
                raise ValidationError("F18 User ID must be between 1 and 500.")
