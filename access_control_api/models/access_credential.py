# -*- coding: utf-8 -*-
from odoo import models, fields, api
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

    _person_credential_type_uniq = models.Constraint(
        "unique(person_id, credential_type)",
        "Only one credential per modality is allowed for each person.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        Change = self.env["access_control.sync_change"].sudo()
        for rec in records:
            if rec.credential_type in ("face", "palm"):
                person = rec.person_id
                if person.active and person.global_user_id and person.site_ids:
                    Change.queue_upsert_for_person(person, reason="credential_create")
        return records

    def write(self, vals):
        old_person_ids = set(self.mapped("person_id").ids)
        res = super().write(vals)

        new_person_ids = set(self.mapped("person_id").ids)
        affected_ids = old_person_ids | new_person_ids
        if affected_ids:
            Change = self.env["access_control.sync_change"].sudo()
            people = self.env["access_control.person"].sudo().browse(list(affected_ids)).exists()
            for person in people:
                if person.active and person.global_user_id and person.site_ids:
                    Change.queue_upsert_for_person(person, reason="credential_write")
        return res

    def unlink(self):
        people = self.mapped("person_id")
        res = super().unlink()
        Change = self.env["access_control.sync_change"].sudo()
        for person in people.exists():
            if person.active and person.global_user_id and person.site_ids:
                Change.queue_upsert_for_person(person, reason="credential_unlink")
        return res

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

            # Choose first active site with configured active enroll device.
            site = rec.person_id.site_ids.filtered(
                lambda s: s.active and s.enroll_device_id and s.enroll_device_id.active
            ).sorted(key=lambda s: s.id)[:1]
            if not site:
                raise ValidationError(
                    "Unable to resolve an enrollment Site with active Enroll Device for this person."
                )

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
