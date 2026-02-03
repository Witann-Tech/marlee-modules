# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import ValidationError


class AccessCredential(models.Model):
    _name = "access_control.credential"
    _description = "Access Credential"
    _rec_name = "display_name"

    active = fields.Boolean(default=True)

    enroll_status = fields.Selection(
        [("draft", "Draft"), ("requested", "Enroll Requested"), ("enrolling", "Enrolling"), ("active", "Active"), ("error", "Error")],
        string="Enroll Status",
        default="draft",
        index=True,
    )


    # Type of credential
    credential_type = fields.Selection(
        [("pin", "PIN"), ("fingerprint", "Fingerprint")],
        string="Type",
        default="pin",
        required=True,
        index=True,
    )

    # For PIN (store hashed later if needed)
    pin_value = fields.Char(string="PIN")

    # For fingerprint templates (VX10.00)
    finger_index = fields.Integer(string="Finger Index")
    template_format = fields.Selection([("zk_vx10", "ZK VX10.00")], default="zk_vx10", string="Template Format")
    template_b64 = fields.Text(string="Template (base64)")

    person_id = fields.Many2one("access_control.person", string="Person", required=True, index=True, ondelete="cascade")

    # Convenience fields for searching/reporting (read-only)
    partner_id = fields.Many2one("res.partner", string="Partner", related="person_id.partner_id", store=True, readonly=True, index=True)
    site_id = fields.Many2one("access_control.site", string="Site", related="person_id.site_id", store=True, readonly=True, index=True)

    note = fields.Char(string="Note")

    # Backward-compat field: do NOT use in UX. Keep to avoid crashes if a stale DB view references it.
    user_id = fields.Many2one("res.users", string="User", index=True)

    display_name = fields.Char(compute="_compute_display_name", store=True)

    def _compute_display_name(self):
        for rec in self:
            if rec.credential_type == "pin":
                rec.display_name = "PIN"
            else:
                rec.display_name = "Fingerprint"


    def action_request_enroll(self):
        """Create an enroll request for this credential (site-scoped)."""
        for rec in self:
            if rec.credential_type != "fingerprint":
                continue
            if not rec.person_id or not rec.person_id.site_id:
                raise ValidationError("Person and Site are required to enroll.")
            if not rec.finger_index and rec.finger_index != 0:
                raise ValidationError("Finger Index is required for fingerprint enrollment.")
            # Create request
            self.env["access_control.enroll_request"].sudo().create({
                "site_id": rec.person_id.site_id.id,
                "credential_id": rec.id,
                "status": "requested",
            })
            rec.enroll_status = "requested"
            rec.person_id.site_id.force_sync = True  # nudge sync after enrollment completes
        return True

    def action_cancel_enroll(self):
        for rec in self:
            if rec.enroll_status in ("requested", "enrolling"):
                # cancel latest open request(s)
                reqs = self.env["access_control.enroll_request"].sudo().search([
                    ("credential_id", "=", rec.id),
                    ("status", "in", ("requested", "enrolling")),
                ])
                reqs.write({"status": "cancelled"})
                rec.enroll_status = "draft"
        return True
