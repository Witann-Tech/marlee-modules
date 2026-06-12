from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    wgs_direct_debit_membership = fields.Boolean(
        string='Domiciliado WGS',
        default=False,
        help=(
            'Activa reglas de domiciliación WGS en POS: plazo forzoso según el plan recurrente, '
            'primer mes proporcional, último mes anticipado y renovaciones mensuales acumulables.'
        ),
    )
