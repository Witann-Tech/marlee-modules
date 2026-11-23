from odoo import _, api, Command, fields, models
from odoo.exceptions import UserError


class CashVendorReconcile(models.TransientModel):
    _name = 'witann.pos.cash.vendor.reconcile'
    _description = 'Conciliar salida de efectivo POS con proveedor'
    _check_company_auto = True

    statement_line_id = fields.Many2one(
        'account.bank.statement.line', string='Salida de efectivo', required=True,
        check_company=True, ondelete='cascade')
    company_id = fields.Many2one(related='statement_line_id.company_id', store=True)
    currency_id = fields.Many2one(related='statement_line_id.currency_id')
    session_id = fields.Many2one(related='statement_line_id.pos_session_id', string='Sesión POS')
    date = fields.Date(related='statement_line_id.date', string='Fecha de la salida')
    payment_ref = fields.Char(related='statement_line_id.payment_ref', string='Motivo de la salida')
    amount = fields.Monetary(compute='_compute_amounts', string='Efectivo a aplicar')
    allocated_amount = fields.Monetary(compute='_compute_amounts', string='Total asignado')
    difference = fields.Monetary(compute='_compute_amounts', string='Por asignar')
    partner_id = fields.Many2one(
        'res.partner', string='Proveedor', required=True, check_company=True,
        domain="[('parent_id', '=', False)]")
    line_ids = fields.One2many(
        'witann.pos.cash.vendor.reconcile.line', 'wizard_id', string='Facturas')

    @api.depends('statement_line_id.amount', 'line_ids.amount')
    def _compute_amounts(self):
        for wizard in self:
            wizard.amount = -wizard.statement_line_id.amount
            wizard.allocated_amount = sum(wizard.line_ids.mapped('amount'))
            wizard.difference = wizard.amount - wizard.allocated_amount

    @api.onchange('partner_id', 'statement_line_id')
    def _onchange_partner(self):
        self.line_ids = [Command.clear()]

    def action_reconcile(self):
        self.ensure_one()
        if not self.line_ids or not self.partner_id:
            raise UserError(_('Selecciona el proveedor y sus facturas.'))
        if any(line.bill_id.commercial_partner_id != self.partner_id.commercial_partner_id
               for line in self.line_ids):
            raise UserError(_('Las facturas deben pertenecer al proveedor seleccionado.'))
        self.statement_line_id._witann_reconcile_vendor_bills([
            (line.bill_id, line.amount) for line in self.line_ids])
        return {'type': 'ir.actions.act_window_close'}


class CashVendorReconcileLine(models.TransientModel):
    _name = 'witann.pos.cash.vendor.reconcile.line'
    _description = 'Aplicación de efectivo POS a factura de proveedor'
    _check_company_auto = True

    wizard_id = fields.Many2one(
        'witann.pos.cash.vendor.reconcile', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='wizard_id.company_id', store=True)
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    bill_id = fields.Many2one(
        'account.move', string='Factura de proveedor', required=True, check_company=True)
    invoice_date = fields.Date(related='bill_id.invoice_date', string='Fecha de factura')
    ref = fields.Char(related='bill_id.ref', string='Referencia proveedor')
    residual = fields.Monetary(related='bill_id.amount_residual', string='Saldo pendiente')
    amount = fields.Monetary(string='Importe a aplicar', required=True)

    @api.onchange('bill_id')
    def _onchange_bill(self):
        for line in self:
            remaining = -line.wizard_id.statement_line_id.amount - sum(
                (line.wizard_id.line_ids - line).mapped('amount'))
            line.amount = min(line.residual, max(0, remaining))
