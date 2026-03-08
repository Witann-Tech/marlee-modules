# -*- coding: utf-8 -*-
from odoo import models, fields


class AccessEvent(models.Model):
    _name = "access_control.access_event"
    _description = "Access Event"
    _order = "occurred_at desc, id desc"

    event_id = fields.Char(required=True, index=True)

    site_id = fields.Many2one("access_control.site", index=True, ondelete="set null")
    device_id = fields.Many2one("access_control.device", index=True, ondelete="set null")
    device_code = fields.Char(index=True)

    person_id = fields.Many2one("access_control.person", index=True, ondelete="set null")
    global_user_id = fields.Integer(index=True)

    modality = fields.Selection(
        [("face", "Face"), ("unknown", "Unknown")],
        default="unknown",
        index=True,
    )
    result = fields.Selection(
        [("allowed", "Allowed"), ("denied", "Denied"), ("error", "Error")],
        default="denied",
        index=True,
    )

    occurred_at = fields.Datetime(required=True, index=True)
    received_at = fields.Datetime(default=fields.Datetime.now, readonly=True)

    raw_payload = fields.Text()

    _sql_constraints = [
        ("uniq_access_event_event_id", "unique(event_id)", "Event ID must be unique."),
    ]
