"""Refund complete purchases without cancelling a later commercial cycle."""

import json

from odoo import _, models
from odoo.exceptions import UserError


class PosSubscriptionRefund(models.Model):
    _inherit = 'pos.order'

    def _wgs_assert_membership_refund_order(self, original):
        """Ordinary membership refunds unwind purchases newest first.

        Reenrollment can reuse a sale.order. Cancelling that order for an older
        receipt would also cancel the later, independently paid membership.
        Domiciliation collections instead reverse their own frozen installments.
        """
        source = original.wgs_sale_order_id
        if not source:
            raise UserError(_('El pago original no identifica su suscripcion.'))
        pricing = json.loads(original.wgs_pricing_snapshot_json or '{}')
        selection = pricing.get('domiciliation') or {}
        if original.wgs_subscription_flow == 'renewal' and selection.get('selection_mode') == 'renewal':
            return
        paid = [('order_id.state', 'in', ['paid', 'done', 'invoiced']), ('qty', '<', 0)]
        later = self.env['pos.order.line'].sudo().search([
            ('id', '>', original.id), ('wgs_sale_order_id', '=', source.id),
            ('order_id.company_id', '=', original.order_id.company_id.id),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']), ('qty', '>', 0),
            ('product_id.recurring_invoice', '=', True),
            ('refund_orderline_ids', 'not any', paid),
            ('wgs_refund_origin_line_ids', 'not any', paid),
        ], order='id desc', limit=1)
        if later:
            raise UserError(_(
                'Esta membresia tiene una compra posterior (%s). '
                'Devuelve primero la compra mas reciente para no cancelar otro periodo pagado.'
            ) % (later.order_id.pos_reference or later.order_id.name))

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
