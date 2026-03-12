# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = "res.partner"

    access_person_ids = fields.One2many(
        "access_control.person",
        "partner_id",
        string="Control de acceso",
    )
