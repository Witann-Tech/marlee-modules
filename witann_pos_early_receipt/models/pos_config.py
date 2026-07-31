from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    wgs_early_receipt_printing = fields.Boolean(
        string='Impresion anticipada de recibo',
        help='Permite imprimir una precuenta antes de registrar el pago, sin activar el modo Bar/Restaurante.',
    )

    def _load_pos_data_fields(self, config_id):
        field_names = super()._load_pos_data_fields(config_id)
        if 'wgs_early_receipt_printing' not in field_names:
            field_names.append('wgs_early_receipt_printing')
        return field_names
