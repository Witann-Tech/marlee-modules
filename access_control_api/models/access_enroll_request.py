# -*- coding: utf-8 -*-
from odoo import models, fields


class AccessEnrollRequest(models.Model):
    _name = "access_control.enroll_request"
    _description = "Enroll Request (site-scoped, ZK9500)"
    _order = "create_date asc"

    site_id = fields.Many2one("access_control.site", string="Site", required=True, index=True, ondelete="cascade")
    credential_id = fields.Many2one("access_control.credential", string="Credential", required=True, index=True, ondelete="cascade")

    person_id = fields.Many2one("access_control.person", related="credential_id.person_id", store=True, readonly=True, index=True)
    partner_id = fields.Many2one("res.partner", related="person_id.partner_id", store=True, readonly=True, index=True)

    finger_index = fields.Integer(related="credential_id.finger_index", store=True, readonly=True)
    template_format = fields.Selection(related="credential_id.template_format", store=True, readonly=True)

    status = fields.Selection(
        [
            ("requested", "Requested"),
            ("enrolling", "Enrolling"),
            ("done", "Done"),
            ("error", "Error"),
            ("cancelled", "Cancelled"),
        ],
        default="requested",
        required=True,
        index=True,
    )

    requested_by = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    requested_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    enrolled_at = fields.Datetime(readonly=True)

    quality = fields.Integer()
    error_code = fields.Char()
    error_message = fields.Text()
