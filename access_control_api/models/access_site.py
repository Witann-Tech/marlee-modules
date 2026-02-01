# -*- coding: utf-8 -*-
from odoo import models, fields

class AccessControlSite(models.Model):
    _name = "access_control.site"
    _description = "Access Control Site"
    _rec_name = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)

    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("access_control_site_code_uniq", "unique(code)", "Site code must be unique."),
    ]
