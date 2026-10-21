from odoo import fields, models


class PosCommissionClaim(models.Model):
    _name = 'witann.pos.commission.claim'
    _description = 'Reserva interna de origen POS por quincena'

    # No ACL: only the private payslip calculation manages these records.
    payslip_id = fields.Many2one('hr.payslip', required=True, ondelete='cascade', index=True)
    config_id = fields.Many2one('pos.config', required=True, ondelete='restrict')
    seller_key = fields.Char(required=True)
    period = fields.Date(required=True)

    _source_period_unique = models.Constraint(
        'UNIQUE(config_id, seller_key, period)',
        'Este origen POS ya tiene una comisión en la misma quincena.',
    )
