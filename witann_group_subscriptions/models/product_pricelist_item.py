from odoo import fields, models


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    wgs_minimum_term_periods = fields.Integer(
        string='Plazo mínimo (periodos)',
        related='plan_id.wgs_minimum_term_periods',
        readonly=False,
        store=False,
        help='Plazo mínimo heredado del plan recurrente seleccionado en esta línea.',
    )
