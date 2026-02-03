# -*- coding: utf-8 -*-
from odoo import models, fields


class AccessCredential(models.Model):
    _name = "access_control.credential"
    _description = "Access Credential (Fingerprint/Card/etc.)"
    _rec_name = "fingerprint_id"

    active = fields.Boolean(default=True)
    fingerprint_id = fields.Char(required=True, index=True)

    # Related to Access Person (which points to res.partner)
    person_id = fields.Many2one(
        "access_control.person", string="Person", required=True, index=True, ondelete="cascade"
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        related="person_id.partner_id",
        store=True,
        readonly=True,
        index=True,
    )

    # Backward-compat field (legacy views may reference it). Not used in new design.
    user_id = fields.Many2one("res.users", string="User", index=True)

    note = fields.Char(string="Note")
