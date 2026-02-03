# -*- coding: utf-8 -*-
from odoo import models, fields

class AccessControlDevice(models.Model):
    _name = "access_control.device"
    _description = "Access Control Device (F18)"
    _rec_name = "name"

    active = fields.Boolean(default=True)

    name = fields.Char(required=True)
    device_code = fields.Char(required=True, index=True)

    site_id = fields.Many2one("access_control.site", required=True, ondelete="cascade")

    ip = fields.Char(required=True)
    port = fields.Integer(default=4370)
    comm_password = fields.Integer(default=0)
    machine_number = fields.Integer(default=1)

    # Telemetry (set by middleware heartbeat)
    last_heartbeat_at = fields.Datetime(string="Last Heartbeat", readonly=True)
    last_sync_at = fields.Datetime(string="Last Sync", readonly=True)
    last_error = fields.Text(string="Last Error", readonly=True)


    _sql_constraints = [
        ("access_control_device_code_uniq", "unique(device_code)", "Device code must be unique."),
    ]
