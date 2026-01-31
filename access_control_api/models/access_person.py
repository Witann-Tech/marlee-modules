# -*- coding: utf-8 -*-
from odoo import models, fields


class AccessPerson(models.Model):
    _name = "access_control.person"
    _description = "Access Control Person (to sync to devices)"
    _rec_name = "name"

    active = fields.Boolean(default=True)

    name = fields.Char(required=True, index=True)

    # PIN opcional (si lo vas a permitir)
    pin = fields.Char()

    # Referencias opcionales para vincular con tu data real
    user_id = fields.Many2one("res.users", string="User")
    partner_id = fields.Many2one("res.partner", string="Partner")

    note = fields.Char()
