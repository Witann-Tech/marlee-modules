from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    max_participants_total = fields.Integer(
        string='Máximo de participantes (total)',
        default=1,
        help='Cantidad total permitida por unidad de suscripción, incluyendo al titular.',
    )
    subscription_minimum_term_periods = fields.Integer(
        string='Plazo mínimo (periodos)',
        default=0,
        help='Cantidad mínima de periodos del plan que debe durar la suscripción. Si es 0, no se exige plazo mínimo.',
    )

    @api.constrains('max_participants_total', 'recurring_invoice', 'subscription_minimum_term_periods')
    def _check_max_participants_total(self):
        for product in self:
            if product.max_participants_total < 0:
                raise ValidationError(
                    _('El máximo de participantes no puede ser negativo.')
                )
            if product.recurring_invoice and product.max_participants_total < 1:
                raise ValidationError(
                    _('Los productos de suscripción deben permitir al menos 1 participante (titular).')
                )
            if product.subscription_minimum_term_periods < 0:
                raise ValidationError(
                    _('El plazo mínimo no puede ser negativo.')
                )
