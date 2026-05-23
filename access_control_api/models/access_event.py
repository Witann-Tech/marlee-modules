# -*- coding: utf-8 -*-
from odoo import models, fields


class AccessEvent(models.Model):
    _name = "access_control.access_event"
    _description = "Evento de Acceso"
    _order = "occurred_at desc, id desc"

    event_id = fields.Char(required=True, index=True)

    site_id = fields.Many2one("access_control.site", index=True, ondelete="set null")
    device_id = fields.Many2one("access_control.device", index=True, ondelete="set null")
    device_serial = fields.Char(index=True)

    person_id = fields.Many2one("access_control.person", index=True, ondelete="set null")
    global_user_id = fields.Integer(index=True)

    modality = fields.Selection(
        [("face", "Rostro"), ("manual_open_door", "Apertura manual"), ("unknown", "Desconocido")],
        default="unknown",
        index=True,
    )
    result = fields.Selection(
        [("allowed", "Permitido"), ("denied", "Denegado"), ("error", "Error")],
        default="denied",
        index=True,
    )

    occurred_at = fields.Datetime(required=True, index=True)
    received_at = fields.Datetime(default=fields.Datetime.now, readonly=True)

    raw_payload = fields.Text()

    _event_id_uniq = models.Constraint(
        "unique(event_id)",
        "El ID del evento debe ser único.",
    )
