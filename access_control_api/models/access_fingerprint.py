# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AccessFingerprint(models.Model):
    _name = "access_control.fingerprint"
    _description = "Fingerprint template storage for Access Control"
    _rec_name = "display_name"

    active = fields.Boolean(default=True)

    person_id = fields.Many2one("access_control.person", required=True, ondelete="cascade", index=True)

    finger_index = fields.Integer(required=True, default=1, help="Finger index (1..10)")
    format = fields.Selection(
        selection=[("zk_vx10", "ZK Finger VX10.00")],
        required=True,
        default="zk_vx10",
    )

    template_b64 = fields.Text(string="Template (base64)", required=True)

    version = fields.Integer(default=1)
    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("person_id", "finger_index")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.person_id.name} - finger {rec.finger_index}"

    @api.constrains("finger_index")
    def _check_finger_index(self):
        for rec in self:
            if rec.finger_index < 1 or rec.finger_index > 10:
                raise ValidationError("finger_index must be between 1 and 10.")

    _sql_constraints = [
        ("access_control_fingerprint_person_finger_uniq", "unique(person_id, finger_index)", "Each person can only have one template per finger index."),
    ]
