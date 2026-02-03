# -*- coding: utf-8 -*-
from odoo import models, fields


class AccessEnrollSession(models.Model):
    _name = "access_control.enroll_session"
    _description = "Enrollment session (worker claims, captures on device, uploads to Odoo)"

    site_code = fields.Char(required=True, index=True)
    person_id = fields.Many2one("access_control.person", required=True, ondelete="cascade", index=True)

    mode = fields.Selection(
        selection=[("fingerprint", "Fingerprint"), ("pin", "PIN")],
        required=True,
        default="fingerprint",
    )

    status = fields.Selection(
        selection=[("pending", "Pending"), ("claimed", "Claimed"), ("completed", "Completed"), ("failed", "Failed"), ("expired", "Expired")],
        required=True,
        default="pending",
        index=True,
    )

    requested_by = fields.Char()
    claimed_by = fields.Char()
    device_id = fields.Char()

    expires_at = fields.Datetime(index=True)
    error_code = fields.Char()
    error_message = fields.Char()
