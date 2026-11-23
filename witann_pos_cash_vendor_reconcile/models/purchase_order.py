from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL, clean_context


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    witann_cash_link_ids = fields.One2many('witann.pos.cash.purchase.link', 'order_id', string='Efectivo POS')

    def _witann_lock_cash(self):
        self.check_access('read')
        self.env.flush_all()
        # Version the PO to serialize reservations and invoice publications,
        # including two new invoices competing for the same remaining cash.
        for order in self.sorted('id'):
            self.env.cr.execute(SQL('UPDATE purchase_order SET write_date = write_date WHERE id = %s', order.id))
        self.env.invalidate_all()

    def _witann_bill_cash_capacity(self, bill):
        self.ensure_one()
        product_lines = bill.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        eligible = (bill.amount_total if product_lines and all(
            l.purchase_line_id.order_id == self for l in product_lines) else sum(
                product_lines.filtered(lambda l: l.purchase_line_id.order_id == self).mapped('price_total')))
        links = self.witann_cash_link_ids.filtered(lambda r: r.state == 'active')
        partials = links.statement_line_id.move_id.line_ids.matched_credit_ids.filtered(
            lambda p: p.credit_move_id.move_id == bill)
        return max(0, bill.currency_id.round(eligible - sum(partials.mapped('amount'))))

    def _witann_apply_cash_to_bills(self, bills):
        self = self.with_context(clean_context(self.env.context))
        bills = bills.with_env(self.env).filtered(lambda b: b.state == 'posted' and b.move_type == 'in_invoice')
        self._witann_lock_cash()
        links = self.witann_cash_link_ids.filtered(lambda r: r.state == 'active' and r.remaining_amount > 0)
        if not links or not bills:
            return
        for link in links:
            if link.source_company_id not in self.env.companies:
                raise UserError(_('Activa la sucursal %(branch)s para aplicar el efectivo de la OC %(order)s.',
                                  branch=link.source_company_id.name, order=link.order_id.name))
        links.statement_line_id._witann_check_accountant()
        links.statement_line_id._witann_lock_reconciliation(bills)
        for order in self.sorted('id'):
            for bill in bills.sorted(lambda b: (b.date, b.id)):
                if order not in bill.invoice_line_ids.purchase_line_id.order_id:
                    continue
                for link in order.witann_cash_link_ids.filtered(lambda r: r.state == 'active').sorted('id'):
                    amount = min(link.remaining_amount, bill.amount_residual, order._witann_bill_cash_capacity(bill))
                    if bill.currency_id.compare_amounts(amount, 0) <= 0:
                        continue
                    link.statement_line_id._witann_reconcile_vendor_bills([(bill, amount)], purchase_link=link)

    def action_witann_apply_cash(self):
        if not self:
            raise UserError(_('La salida no tiene una OC vinculada.'))
        self._witann_apply_cash_to_bills(self.invoice_ids)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def write(self, vals):
        if set(vals) & {'partner_id', 'currency_id', 'company_id', 'state'}:
            self._witann_lock_cash()
            for order in self:
                linked = order.witann_cash_link_ids.filtered(lambda r: r.state == 'active')
                changed = any(k in vals and vals[k] != order[k].id for k in ('partner_id', 'currency_id', 'company_id'))
                if linked and (changed or vals.get('state') in ('cancel', 'draft')):
                    raise UserError(_('Desvincula las salidas de efectivo antes de cambiar proveedor, moneda, empresa o cancelar la OC.'))
        return super().write(vals)
