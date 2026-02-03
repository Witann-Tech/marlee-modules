# -*- coding: utf-8 -*-
from odoo import models, fields, api

class AccessControlSite(models.Model):
    _name = "access_control.site"
    _description = "Access Control Site"
    _rec_name = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)

    active = fields.Boolean(default=True)

    device_ids = fields.One2many('access_control.device', 'site_id', string='Devices')

    force_sync = fields.Boolean(string="Force Sync", default=False,
                               help="If enabled, worker should sync even if site_version did not change.")

    slots_used = fields.Integer(string="Slots Used", compute="_compute_slots", store=False)
    slots_total = fields.Integer(string="Slots Total", compute="_compute_slots", store=False)
    slots_percent = fields.Float(string="Slots Usage %", compute="_compute_slots", store=False)
    near_limit = fields.Boolean(string="Near Limit", compute="_compute_slots", store=False)

    @api.depends('device_ids', 'code')
    def _compute_slots(self):
        Person = self.env['access_control.person'].sudo()
        for site in self:
            used = Person.search_count([('site_id', '=', site.id), ('f18_user_id', '!=', False)])
            total = 500
            site.slots_used = used
            site.slots_total = total
            site.slots_percent = (used / total * 100.0) if total else 0.0
            site.near_limit = used >= int(total * 0.9)


    _sql_constraints = [
        ("access_control_site_code_uniq", "unique(code)", "Site code must be unique."),
    ]
