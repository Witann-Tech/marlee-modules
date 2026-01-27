# -*- coding: utf-8 -*-
from odoo import models, fields


class AccessCredential(models.Model):
    _name = "access_control.credential"
    _description = "Access Credential (Fingerprint/Card/etc.)"
    _rec_name = "fingerprint_id"

    active = fields.Boolean(default=True)
    fingerprint_id = fields.Char(required=True, index=True)

    # Mixto: puede apuntar a un usuario interno (staff) o a un partner (miembro/cliente)
    user_id = fields.Many2one("res.users", string="User")
    partner_id = fields.Many2one("res.partner", string="Partner")

    note = fields.Char()
