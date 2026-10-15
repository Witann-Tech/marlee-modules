"""Postconditions of native Odoo 19 subscription applications.

Commercial quotes describe a purchase, sale.order owns its active plan/period,
and domiciliation owns installment balances. No balances are duplicated here.
"""

from odoo import _, fields, models
from odoo.exceptions import UserError


class PosSubscriptionApplication(models.Model):
    _inherit = 'pos.order'

    def _wgs_assert_subscription_refund(self, subscription):
        if subscription.state != 'cancel' and subscription._wgs_get_subscription_state_category() not in ('closed', 'cancel'):
            raise UserError(_('El reembolso total no cancelo la membresia original.'))
        pending = self.env['pos.order.line'].search([
            ('wgs_subscription_source_id', '=', subscription.id),
            ('wgs_application_state', 'in', ['scheduled', 'review']),
        ], limit=1)
        contract = subscription.wgs_domiciliation_contract_id
        if pending or (contract and contract.state != 'cancelled'):
            raise UserError(_('El reembolso no cancelo todos los cambios y cobros domiciliados pendientes.'))

    def _wgs_assert_subscription_application(
        self, line, subscription, pricing, *, before, activation=False, expected_participants=False,
    ):
        """Reject a partial native application inside Odoo's existing transaction."""
        subscription.ensure_one()
        if subscription.company_id != self.company_id or subscription.partner_id != self.partner_id:
            raise UserError(_('La membresia aplicada no corresponde al titular y empresa del cobro.'))
        snapshot = pricing['snapshot']
        if line.wgs_application_state == 'scheduled' and not activation:
            if (subscription != line.wgs_subscription_source_id
                    or line.wgs_application_date != pricing['subscription_start_date']
                    or self._wgs_source_revision(subscription) != before):
                raise UserError(_('El cambio programado debe conservar intacta la membresia vigente.'))
            return

        # Read back persisted fields, not only values prepared by a handler.
        subscription.flush_recordset()
        subscription.order_line.flush_recordset()
        subscription.invalidate_recordset(['plan_id', 'end_date', 'next_invoice_date', 'order_line', 'participant_ids'])
        recurring = subscription.order_line.filtered(
            lambda item: item.product_id.recurring_invoice and item.product_uom_qty > 0
        )
        if (subscription.plan_id.id != pricing['plan_id']
                or len(recurring) != 1 or recurring.product_id != line.product_id):
            raise UserError(_('El paquete o plan aplicado no coincide con la cotizacion pagada.'))
        if (abs(recurring.product_uom_qty - abs(line.qty)) > 0.00001
                or subscription.currency_id.compare_amounts(recurring.price_unit, pricing['price_unit'])
                or recurring.discount):
            raise UserError(_('El contrato no conserva la cantidad y precio recurrente cotizados.'))

        if expected_participants is False:
            expected_participants = set(self._wgs_resolve_subscription_participant_ids_for_pos_line(
                line=line, holder_partner=self.partner_id, product=line.product_id, qty=abs(line.qty),
            ))
        if set(subscription.participant_ids.ids) != expected_participants:
            raise UserError(_('Los participantes aplicados no coinciden con el paquete pagado.'))

        domiciliation = snapshot.get('domiciliation') or {}
        if domiciliation.get('is_domiciliation'):
            self._wgs_assert_domiciliation_application(line, subscription, pricing, domiciliation)
            return
        if (subscription.end_date != pricing['subscription_end_date']
                or subscription.next_invoice_date != pricing['next_billing_date']
                or subscription.wgs_monthly_cutoff_day != pricing['monthly_cutoff_day']):
            raise UserError(_('La vigencia aplicada no coincide con la vigencia contratada.'))
        if line.wgs_subscription_flow in ('new', 'reenroll', 'upsale'):
            start = subscription.wgs_effective_start_date or subscription.start_date
            if start != pricing['subscription_start_date']:
                raise UserError(_('El inicio aplicado no coincide con el inicio contratado.'))

    def _wgs_assert_domiciliation_application(self, line, subscription, pricing, domiciliation):
        contract = subscription.wgs_domiciliation_contract_id
        if (not contract or contract.state != 'active'
                or contract.subscription_id != subscription or contract.company_id != self.company_id
                or contract.partner_id != self.partner_id or contract.product_id != line.product_id
                or contract.plan_id.id != pricing['plan_id']
                or contract.currency_id.compare_amounts(contract.monthly_amount, pricing['price_unit'])):
            raise UserError(_('El contrato domiciliado aplicado no coincide con el contratado.'))
        sequences = domiciliation.get('selected_installment_sequences') or []
        paid = contract.installment_ids.filtered(lambda item: item.sequence in sequences)
        if not sequences or len(paid) != len(sequences) or any(
            item.state != 'paid' or item.paid_pos_line_id != line for item in paid
        ):
            raise UserError(_('Las mensualidades seleccionadas no quedaron aplicadas al pago.'))
        if domiciliation.get('selection_mode') == 'initial' and contract.access_start_date != fields.Date.to_date(
            pricing['subscription_start_date']
        ):
            raise UserError(_('El inicio del contrato domiciliado no coincide con el contratado.'))
