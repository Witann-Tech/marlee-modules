from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    wgs_early_receipt_printing = fields.Boolean(
        string='Impresion anticipada de recibo',
        help='Permite imprimir una precuenta antes de registrar el pago, sin activar el modo Bar/Restaurante.',
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        field_names = list(super()._load_pos_data_fields(config_id))
        # pos.config._load_pos_data_read consumes this field unconditionally.
        # Keep the native loader contract intact even when another addon changes
        # the parent field collection.
        for field_name in ('use_pricelist', 'wgs_early_receipt_printing'):
            if field_name not in field_names:
                field_names.append(field_name)
        return field_names
