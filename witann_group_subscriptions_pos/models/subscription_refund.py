"""Reverse a complete domiciliation collection, not its historical contract."""

from odoo import _, models
from odoo.exceptions import UserError


class PosSubscriptionRefund(models.Model):
    _inherit = 'pos.order'

    def _wgs_refund_domiciliation_collection(self, line, original):
        self.ensure_one()
        if not original or line.wgs_subscription_flow == 'cancellation_refund':
            return False
        subscription = original.wgs_sale_order_id
        contract = subscription.wgs_domiciliation_contract_id
        if original.wgs_subscription_flow != 'renewal' or not contract:
            return False
        pricing = original.order_id._wgs_get_persisted_subscription_pricing_from_pos_line(original)
        selection = (pricing.get('snapshot') or {}).get('domiciliation') or {}
        if original.wgs_subscription_flow != 'renewal' or selection.get('selection_mode') != 'renewal':
            return False
        sequences = selection.get('selected_installment_sequences') or []
        if (not contract or contract.state != 'active' or selection.get('contract_id') != contract.id
                or not sequences or subscription.partner_id != self.partner_id):
            raise UserError(_('La devolucion debe identificar el contrato y las cuotas originales.'))
        installments = contract.installment_ids.filtered(lambda item: item.sequence in sequences)
        if (len(installments) != len(sequences)
                or any(item.state != 'paid' or item.paid_pos_line_id != original for item in installments)):
            raise UserError(_('Las mensualidades ya cambiaron o fueron devueltas; no repitas la devolucion.'))
        before = self._wgs_domiciliation_collection_state(subscription, selected_sequences=sequences)
        # Keep the original payment links as evidence. A later collection can
        # settle the due installments; both immutable POS receipts retain history.
        installments.write({'state': 'due'})
        if self._wgs_domiciliation_collection_state(subscription, selected_sequences=sequences) != before:
            raise UserError(_('La devolucion no debe cambiar el contrato ni otras mensualidades.'))
        line.write({
            'wgs_sale_order_id': subscription.id,
            'wgs_application_receipt': {'collection_refund': {
                'contract_id': contract.id, 'original_line_id': original.id,
                'installment_ids': installments.ids, 'sequences': sequences,
            }},
        })
        subscription.message_post(body=_('Devolucion total del cobro POS %(ticket)s; cuotas %(months)s nuevamente pendientes.') % {
            'ticket': original.order_id.pos_reference, 'months': str(sequences),
        })
        return True
