from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    wgs_minimum_term_periods = fields.Integer(
        string='Plazo mínimo (periodos)',
        compute='_compute_wgs_minimum_term_periods',
        inverse='_inverse_wgs_minimum_term_periods',
        help='Plazo mínimo del plan recurrente relacionado a esta línea.',
    )

    def _wgs_get_subscription_plan(self):
        self.ensure_one()
        preferred_names = ('plan_id', 'subscription_plan_id', 'recurring_plan_id', 'recurrence_id')
        for field_name in preferred_names:
            if field_name not in self._fields:
                continue
            field = self._fields[field_name]
            if field.type != 'many2one':
                continue
            if getattr(field, 'comodel_name', '') != 'sale.subscription.plan':
                continue
            if self[field_name]:
                return self[field_name]

        for field_name, field in self._fields.items():
            if field.type != 'many2one':
                continue
            if getattr(field, 'comodel_name', '') != 'sale.subscription.plan':
                continue
            value = self[field_name]
            if value:
                return value
        return False

    def _compute_wgs_minimum_term_periods(self):
        for line in self:
            plan = line._wgs_get_subscription_plan()
            line.wgs_minimum_term_periods = int(getattr(plan, 'wgs_minimum_term_periods', 0) or 0)

    def _inverse_wgs_minimum_term_periods(self):
        for line in self:
            plan = line._wgs_get_subscription_plan()
            if not plan:
                continue
            plan.wgs_minimum_term_periods = int(line.wgs_minimum_term_periods or 0)

    @api.constrains('wgs_minimum_term_periods')
    def _check_wgs_minimum_term_periods(self):
        for line in self:
            if int(line.wgs_minimum_term_periods or 0) < 0:
                raise ValidationError(_('El plazo mínimo no puede ser negativo.'))
