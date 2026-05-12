# -*- coding: utf-8 -*-
from odoo import models, fields


class AccessControlDevice(models.Model):
    _name = "access_control.device"
    _description = "Dispositivo de Control de Acceso (SpeedFace)"
    _rec_name = "name"

    active = fields.Boolean(default=True)

    name = fields.Char(required=True)
    device_serial = fields.Char(required=True, index=True)

    site_id = fields.Many2one("access_control.site", required=True, ondelete="cascade")

    user_capacity = fields.Integer(string="Capacidad de usuarios", default=10000)

    # Telemetría (actualizada por middleware/ADMS)
    last_heartbeat_at = fields.Datetime(string="Último heartbeat", readonly=True)
    last_sync_at = fields.Datetime(string="Última sincronización", readonly=True)
    last_error = fields.Text(string="Último error", readonly=True)

    _device_serial_uniq = models.Constraint(
        "unique(device_serial)",
        "El serial del dispositivo debe ser único.",
    )
    _user_capacity_positive = models.Constraint(
        "CHECK(user_capacity IS NULL OR user_capacity > 0)",
        "La capacidad de usuarios debe ser mayor a cero.",
    )
