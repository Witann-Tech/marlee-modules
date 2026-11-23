from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def action_witann_cash_vendor_reconciliation(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'witann_pos_cash_vendor_reconcile.action_cash_out')
        action['domain'] = [
            ('pos_session_id', '=', self.id), ('amount', '<', 0),
            ('journal_id.type', '=', 'cash'),
        ]
        action['context'] = {'search_default_pending': 1}
        return action
