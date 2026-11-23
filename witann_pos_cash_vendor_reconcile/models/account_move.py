from odoo import _, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        bills = posted.filtered(lambda b: b.move_type == 'in_invoice' and b.state == 'posted')
        orders = bills.invoice_line_ids.purchase_line_id.order_id
        if orders:
            orders._witann_apply_cash_to_bills(bills)
        return posted

    def button_draft(self):
        bills = self.filtered(lambda m: m.move_type == 'in_invoice')
        cash = bills.line_ids.matched_debit_ids.debit_move_id.move_id.statement_line_id
        if cash.filtered('witann_purchase_order_id'):
            raise UserError(_('Deshaz las aplicaciones desde la salida de efectivo antes de devolver la factura a borrador.'))
        return super().button_draft()
