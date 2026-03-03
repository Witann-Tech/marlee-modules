# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import ValidationError


class AccessCredential(models.Model):
    _name = "access_control.credential"
    _description = "Access Credential"
    _rec_name = "display_name"

    active = fields.Boolean(default=True)

    enroll_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("requested", "Enroll Requested"),
            ("enrolling", "Enrolling"),
            ("active", "Active"),
            ("error", "Error"),
        ],
        string="Enroll Status",
        default="draft",
        index=True,
    )

    credential_type = fields.Selection(
        [("face", "Face"), ("palm", "Palm")],
        string="Type",
        default="face",
        required=True,
        index=True,
    )

    biometric_format = fields.Char(string="Biometric Format")
    biometric_b64 = fields.Text(string="Biometric Template (base64)")

    person_id = fields.Many2one("access_control.person", string="Person", required=True, index=True, ondelete="cascade")

    partner_id = fields.Many2one("res.partner", string="Partner", related="person_id.partner_id", store=True, readonly=True, index=True)
    site_ids = fields.Many2many("access_control.site", related="person_id.site_ids", readonly=True)
    site_id = fields.Many2one("access_control.site", compute="_compute_primary_site", readonly=True)

    note = fields.Char(string="Note")

    display_name = fields.Char(compute="_compute_display_name", store=True)

    _sql_constraints = [
        (
            "uniq_person_credential_type",
            "unique(person_id, credential_type)",
            "Only one credential per modality is allowed for each person.",
        ),
    ]

    def _compute_display_name(self):
        for rec in self:
            if rec.credential_type == "face":
                rec.display_name = "Face"
            else:
                rec.display_name = "Palm"

    def _compute_primary_site(self):
        for rec in self:
            rec.site_id = rec.site_ids.sorted(key=lambda s: s.id)[:1].id if rec.site_ids else False

    def action_request_enroll(self):
        """Create a site-scoped enroll request for this credential."""
        for rec in self:
            if not rec.person_id or not rec.person_id.site_ids:
                raise ValidationError("Person must be assigned to at least one Site before enrollment.")

            # If person belongs to multiple sites, pick the first one by ID as default enrollment site.
            site = rec.person_id.site_ids.sorted(key=lambda s: s.id)[:1]
            if not site:
                raise ValidationError("Unable to resolve an enrollment Site for this person.")

            self.env["access_control.enroll_request"].sudo().create(
                {
                    "site_id": site.id,
                    "credential_id": rec.id,
                    "status": "requested",
                }
            )
            rec.enroll_status = "requested"
            site.force_sync = True
        return True

    def action_cancel_enroll(self):
        for rec in self:
            if rec.enroll_status in ("requested", "enrolling"):
                reqs = self.env["access_control.enroll_request"].sudo().search(
                    [
                        ("credential_id", "=", rec.id),
                        ("status", "in", ("requested", "enrolling")),
                    ]
                )
                reqs.write({"status": "cancelled"})
                rec.enroll_status = "draft"
        return True
