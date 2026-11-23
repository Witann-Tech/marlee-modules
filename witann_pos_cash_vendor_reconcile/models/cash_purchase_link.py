from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import clean_context


class CashPurchaseLink(models.Model):
    _name = 'witann.pos.cash.purchase.link'
    _description = 'Reserva de efectivo POS para orden de compra'
    _rec_name = 'order_id'
    _order = 'id'
    _check_company_auto = True

    statement_line_id = fields.Many2one(
        'account.bank.statement.line', required=True, readonly=True, ondelete='restrict', index=True)
    order_id = fields.Many2one('purchase.order', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='order_id.company_id', store=True, index=True)
    source_company_id = fields.Many2one(related='statement_line_id.company_id', store=True, string='Sucursal de caja')
    currency_id = fields.Many2one(related='order_id.currency_id')
    amount = fields.Monetary(readonly=True, string='Efectivo reservado')
    state = fields.Selection([('active', 'Vinculada'), ('cancelled', 'Desvinculada')],
                             required=True, default='active', readonly=True, index=True)
    applied_amount = fields.Monetary(compute='_compute_amounts', store=True, string='Aplicado')
    remaining_amount = fields.Monetary(compute='_compute_amounts', store=True, string='Por aplicar')

    @api.depends('state', 'amount', 'statement_line_id.move_id.line_ids',
                 'statement_line_id.move_id.line_ids.matched_credit_ids.amount',
                 'statement_line_id.move_id.line_ids.matched_credit_ids.credit_move_id.move_id.move_type')
    def _compute_amounts(self):
        # Stored reservation totals are visible on the PO, even when its cash
        # branch is not selected. Applying them always checks the user's actual
        # accounting rights and active companies; no elevated writes are used.
        for link in self:
            partials = link.statement_line_id.move_id.line_ids.matched_credit_ids.filtered(
                lambda p: p.credit_move_id.move_id.move_type == 'in_invoice')
            link.applied_amount = link.currency_id.round(sum(partials.mapped('amount'))) if link.state == 'active' else 0
            link.remaining_amount = max(0, link.currency_id.round(link.amount - link.applied_amount)) if link.state == 'active' else 0

    @api.model_create_multi
    def create(self, vals_list):
        self = self.with_context(clean_context(self.env.context))
        prepared = []
        orders = self.env['purchase.order'].browse([v.get('order_id') for v in vals_list if v.get('order_id')])
        orders._witann_lock_cash()
        for vals in vals_list:
            if set(vals) - {'statement_line_id', 'order_id'}:
                raise UserError(_('Usa el asistente para vincular la salida y la OC.'))
            cash = self.env['account.bank.statement.line'].browse(vals.get('statement_line_id')).exists()
            order = self.env['purchase.order'].browse(vals.get('order_id')).exists()
            if not cash or not order:
                raise UserError(_('Selecciona una salida y una OC existentes.'))
            cash.ensure_one()
            order.ensure_one()
            cash._witann_check_accountant()
            order.check_access('read')
            cash._witann_lock_reconciliation(self.env['account.move'])
            if (cash.witann_vendor_reconciliation_state != 'pending'
                    or cash.journal_id != cash.pos_session_id.cash_journal_id
                    or cash.company_id not in self.env.companies):
                raise UserError(_('La salida debe estar pendiente y su sucursal debe estar activa.'))
            if (order.state != 'purchase' or cash.company_id.root_id != order.company_id.root_id
                    or order.company_id not in self.env.companies):
                raise UserError(_('Selecciona una OC confirmada de la misma empresa matriz y activa sus empresas.'))
            if (cash.currency_id != order.currency_id or cash.currency_id != cash.company_id.currency_id
                    or cash.foreign_currency_id):
                raise UserError(_('La salida y la OC deben estar en la moneda de la empresa.'))
            if (order.partner_id.company_id
                    and order.partner_id.company_id.root_id != cash.company_id.root_id):
                raise UserError(_('El proveedor debe pertenecer a la misma empresa matriz.'))
            if self.search_count([('statement_line_id', '=', cash.id), ('state', '=', 'active')]):
                raise UserError(_('La salida ya está vinculada a una OC.'))
            reserved = sum(order.witann_cash_link_ids.filtered(lambda r: r.state == 'active').mapped('amount'))
            reserved += sum(v['amount'] for v in prepared if v['order_id'] == order.id)
            if order.currency_id.compare_amounts(reserved - cash.amount, order.amount_total) > 0:
                raise UserError(_('El efectivo reservado supera el total de la OC.'))
            if any(v['statement_line_id'] == cash.id for v in prepared):
                raise UserError(_('Selecciona cada salida una sola vez.'))
            prepared.append({**vals, 'amount': -cash.amount, 'state': 'active'})
        links = super().create(prepared)
        for link in links:
            message = _('Salida de efectivo %(cash)s reservada para OC %(order)s. Importe: %(amount)s %(currency)s.',
                        cash=link.statement_line_id.display_name, order=link.order_id.name,
                        amount=link.amount, currency=link.currency_id.name)
            link.statement_line_id.move_id.message_post(body=message)
            link.order_id.message_post(body=message)
        return links

    def write(self, vals):
        if set(vals) & {'order_id', 'statement_line_id', 'amount', 'state', 'company_id',
                        'source_company_id', 'currency_id', 'applied_amount', 'remaining_amount'}:
            raise UserError(_('Los vínculos de efectivo se modifican mediante sus acciones.'))
        return super().write(vals)

    def _check_application(self, cash, bills):
        self.ensure_one()
        if self.state != 'active' or self.statement_line_id != cash or self.order_id.state != 'purchase':
            raise UserError(_('El vínculo con la OC no está disponible para aplicar efectivo.'))
        if any(b.commercial_partner_id != self.order_id.partner_id.commercial_partner_id
               or self.order_id not in b.invoice_line_ids.purchase_line_id.order_id for b in bills):
            raise UserError(_('La factura debe corresponder al proveedor y a las líneas nativas de la OC vinculada.'))

    def action_cancel(self):
        self = self.with_context(clean_context(self.env.context))
        self.order_id._witann_lock_cash()
        for link in self:
            cash = link.statement_line_id
            cash._witann_check_accountant()
            cash._witann_lock_reconciliation(cash.witann_vendor_bill_ids)
            if link.state != 'active':
                raise UserError(_('El vínculo ya está desvinculado.'))
            if not link.currency_id.is_zero(link.applied_amount):
                raise UserError(_('Deshaz las aplicaciones de la salida antes de desvincular la OC.'))
            if cash.witann_vendor_reconciliation_state != 'reserved':
                raise UserError(_('Restaura la conciliación de la salida antes de desvincularla.'))
            super(CashPurchaseLink, link).write({'state': 'cancelled'})
            message = _('Se desvinculó la salida %(cash)s de la OC %(order)s. El efectivo vuelve a estar disponible.',
                        cash=cash.display_name, order=link.order_id.name)
            cash.move_id.message_post(body=message)
            link.order_id.message_post(body=message)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.ondelete(at_uninstall=False)
    def _prevent_history_deletion(self):
        raise UserError(_('Desvincula la OC; el historial de la reserva no se elimina.'))
