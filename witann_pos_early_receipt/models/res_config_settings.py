from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    wgs_early_receipt_printing = fields.Boolean(
        related='pos_config_id.wgs_early_receipt_printing',
        readonly=False,
    )
