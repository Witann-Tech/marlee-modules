from odoo import fields, models


class CashPurchaseWizard(models.TransientModel):
    _name = 'witann.pos.cash.purchase.wizard'
    _description = 'Vincular salida POS con orden de compra'

    statement_line_id = fields.Many2one('account.bank.statement.line', required=True, readonly=True)
    company_id = fields.Many2one(related='statement_line_id.company_id', store=True)
    accounting_company_id = fields.Many2one(related='statement_line_id.company_id.root_id')
    currency_id = fields.Many2one(related='statement_line_id.currency_id')
    amount = fields.Monetary(related='statement_line_id.amount', string='Salida de efectivo')
    order_id = fields.Many2one('purchase.order', required=True, string='Orden de compra')

    def action_link(self):
        self.ensure_one()
        self.env['witann.pos.cash.purchase.link'].create({
            'statement_line_id': self.statement_line_id.id, 'order_id': self.order_id.id})
        return {'type': 'ir.actions.act_window_close'}
