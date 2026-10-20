from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrPayslipInput(models.Model):
    _inherit = 'hr.payslip.input'

    witann_pos_commission = fields.Boolean(readonly=True, copy=False, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('witann_pos_commission') for vals in vals_list):
            raise ValidationError(_('La entrada de comisión POS se genera al calcular el recibo.'))
        return super().create(vals_list)

    def write(self, vals):
        if self.filtered('witann_pos_commission') or 'witann_pos_commission' in vals:
            raise ValidationError(_('Recalcule el recibo para actualizar su comisión POS.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered('witann_pos_commission'):
            raise ValidationError(_('Recalcule el recibo para retirar o actualizar su comisión POS.'))
        return super().unlink()

    def _witann_sync_pos_commission(self, payslip, amount):
        """Private ORM entry point: never trust a context flag from RPC."""
        managed = payslip.input_line_ids.filtered('witann_pos_commission')
        if not amount:
            return super(HrPayslipInput, managed).unlink()
        values = {
            'name': 'Comisión por venta',
            'input_type_id': self.env.ref('l10n_mx_hr_payroll.l10n_mx_input_commissions').id,
            'amount': amount,
            'witann_pos_commission': True,
        }
        if managed:
            super(HrPayslipInput, managed[:1]).write(values)
            super(HrPayslipInput, managed[1:]).unlink()
        else:
            super(HrPayslipInput, self).create(dict(values, payslip_id=payslip.id))
