from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleSubscriptionPlan(models.Model):
    _inherit = 'sale.subscription.plan'

    wgs_minimum_term_periods = fields.Integer(
        string='Plazo mínimo (periodos)',
        default=0,
        help=(
            'Cantidad mínima de periodos que debe durar la suscripción para este plan recurrente. '
            'Si es 0, no se exige plazo mínimo.'
        ),
    )

    @api.constrains('wgs_minimum_term_periods')
    def _check_wgs_minimum_term_periods(self):
        for plan in self:
            if int(plan.wgs_minimum_term_periods or 0) < 0:
                raise ValidationError(_('El plazo mínimo no puede ser negativo.'))
