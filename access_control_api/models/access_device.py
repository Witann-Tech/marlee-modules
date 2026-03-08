# -*- coding: utf-8 -*-
from odoo import models, fields


class AccessControlDevice(models.Model):
    _name = "access_control.device"
    _description = "Access Control Device (SpeedFace)"
    _rec_name = "name"

    active = fields.Boolean(default=True)

    name = fields.Char(required=True)
    device_serial = fields.Char(required=True, index=True, oldname="device_code")

    site_id = fields.Many2one("access_control.site", required=True, ondelete="cascade")

    user_capacity = fields.Integer(string="User Capacity", default=10000)

    # Telemetry (set by middleware heartbeat)
    last_heartbeat_at = fields.Datetime(string="Last Heartbeat", readonly=True)
    last_sync_at = fields.Datetime(string="Last Sync", readonly=True)
    last_error = fields.Text(string="Last Error", readonly=True)

    _sql_constraints = [
        ("access_control_device_serial_uniq", "unique(device_serial)", "Device serial must be unique."),
        (
            "check_user_capacity_positive",
            "CHECK(user_capacity IS NULL OR user_capacity > 0)",
            "User capacity must be greater than zero.",
        ),
    ]
