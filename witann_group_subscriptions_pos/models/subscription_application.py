"""Postconditions of native Odoo 19 subscription applications.

Commercial quotes describe a purchase, sale.order owns its active plan/period,
and domiciliation owns installment balances. No balances are duplicated here.
"""

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..subscription_contract import fingerprint


class PosSubscriptionApplication(models.Model):
    _inherit = 'pos.order'

    def _wgs_domiciliation_collection_state(self, subscription, *, selected_sequences=()):
        """Freeze commercial identity and all ledger fields except this payment."""
        contract = subscription.wgs_domiciliation_contract_id
        native = self._wgs_source_contract(subscription)
        native.pop('installments')
        ledger = []
        for item in contract.installment_ids.sorted('sequence'):
            values = {
                'id': item.id, 'sequence': item.sequence, 'kind': item.kind,
                'start': str(item.period_start_date), 'end': str(item.period_end_date),
                'due': str(item.due_date), 'amount': item.amount, 'source': item.payment_source,
            }
            if item.sequence not in selected_sequences:
                values.update(state=item.state, order=item.paid_pos_order_id.id,
                              line=item.paid_pos_line_id.id, at=str(item.paid_at or ''))
            ledger.append(values)
        return {
            'subscription': native, 'contract': contract.id, 'state': contract.state,
            'owner': contract.partner_id.id, 'company': contract.company_id.id,
            'product': contract.product_id.id, 'plan': contract.plan_id.id,
            'currency': contract.currency_id.id, 'monthly': contract.monthly_amount,
            'access_start': str(contract.access_start_date), 'term_start': str(contract.term_start_date),
            'term_end': str(contract.term_end_date), 'months': contract.term_months,
            'ledger': ledger,
        }

    def _wgs_domiciliation_collection_revision(self, subscription):
        return fingerprint(self._wgs_domiciliation_collection_state(subscription))

    def _wgs_validate_domiciliation_collection_quote(self, subscription, snapshot):
        contract = subscription.wgs_domiciliation_contract_id
        quote = snapshot.get('domiciliation') or {}
        if (not contract or contract.state != 'active' or not quote.get('is_domiciliation')
                or contract.subscription_id != subscription or contract.partner_id != subscription.partner_id
                or contract.company_id != subscription.company_id or contract.currency_id != subscription.currency_id
                or quote.get('selection_mode') != 'renewal' or quote.get('contract_id') != contract.id
                or quote.get('collection_revision') != self._wgs_domiciliation_collection_revision(subscription)
                or snapshot.get('plan_id') != contract.plan_id.id
                or contract.currency_id.compare_amounts(snapshot.get('recurring_price', -1), contract.monthly_amount)):
            raise UserError(_(
                'La cotizacion domiciliada no corresponde a la cartera actual. '
                'Actualiza la seleccion de mensualidades antes de cobrar; no repitas un pago ya recibido.'
            ))

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

    def _wgs_assert_domiciliation_collection_application(self, line, subscription, pricing, before):
        """Collect the wallet without rewriting the historical native sale.

        Imported wallets can intentionally differ from the native sale's old
        plan or discounted price. The wallet owns this collection's terms; the
        frozen native footprint must remain exactly as it was before payment.
        """
        domiciliation = pricing['snapshot']['domiciliation']
        contract = subscription.wgs_domiciliation_contract_id
        contract.flush_recordset()
        contract.installment_ids.flush_recordset()
        contract.invalidate_recordset()
        contract.installment_ids.invalidate_recordset()
        if (not before or line.qty != 1 or subscription != line.wgs_subscription_source_id
                or self._wgs_domiciliation_collection_state(
                    subscription, selected_sequences=domiciliation.get('selected_installment_sequences') or [],
                ) != before):
            raise UserError(_('La cobranza domiciliada no debe modificar el contrato ni los pagos anteriores.'))
        self._wgs_assert_domiciliation_application(line, subscription, pricing, domiciliation)

    def _wgs_assert_subscription_application(
        self, line, subscription, pricing, *, before, activation=False, expected_participants=False,
        preserved_source=False,
        collection_before=False,
    ):
        """Reject a partial native application inside Odoo's existing transaction."""
        subscription.ensure_one()
        if subscription.company_id != self.company_id or subscription.partner_id != self.partner_id:
            raise UserError(_('La membresia aplicada no corresponde al titular y empresa del cobro.'))
        if preserved_source:
            if (subscription == preserved_source or subscription.wgs_reenrollment_source_id != preserved_source
                    or self._wgs_source_revision(preserved_source) != before):
                raise UserError(_('La reinscripcion de un participante debe conservar intacto el contrato historico.'))
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
        if len(recurring) != 1 or recurring.product_id != line.product_id:
            raise UserError(_('El paquete o plan aplicado no coincide con la cotizacion pagada.'))
        domiciliation = snapshot.get('domiciliation') or {}
        collection = (
            line.wgs_subscription_flow == 'renewal' and domiciliation.get('is_domiciliation')
            and domiciliation.get('selection_mode') == 'renewal'
        )
        if collection:
            self._wgs_assert_domiciliation_collection_application(
                line, subscription, pricing, collection_before,
            )
            return

        if subscription.plan_id.id != pricing['plan_id']:
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

        if line.wgs_subscription_flow == 'upsale':
            source = line.wgs_subscription_source_id
            if not source or source == subscription or source._wgs_get_subscription_state_category() not in ('closed', 'cancel'):
                raise UserError(_('El upsale no cerro la membresia sustituida.'))

        if domiciliation.get('is_domiciliation'):
            self._wgs_assert_domiciliation_application(line, subscription, pricing, domiciliation)
            return
        if (fields.Date.to_date(subscription.end_date) != fields.Date.to_date(pricing['subscription_end_date'])
                or fields.Date.to_date(subscription.next_invoice_date) != fields.Date.to_date(pricing['next_billing_date'])
                or subscription.wgs_monthly_cutoff_day != pricing['monthly_cutoff_day']):
            raise UserError(_('La vigencia aplicada no coincide con la vigencia contratada.'))
        if line.wgs_subscription_flow in ('new', 'reenroll', 'upsale'):
            start = subscription.wgs_effective_start_date or subscription.start_date
            if fields.Date.to_date(start) != fields.Date.to_date(pricing['subscription_start_date']):
                raise UserError(_('El inicio aplicado no coincide con el inicio contratado.'))

    def _wgs_assert_domiciliation_application(self, line, subscription, pricing, domiciliation):
        contract = subscription.wgs_domiciliation_contract_id
        if (not contract or contract.state != 'active'
                or contract.subscription_id != subscription or contract.company_id != self.company_id
                or contract.partner_id != self.partner_id or contract.product_id != line.product_id
                or contract.plan_id.id != pricing['plan_id']
                or contract.currency_id != subscription.currency_id
                or (domiciliation.get('selection_mode') == 'renewal' and domiciliation.get('contract_id') != contract.id)
                or contract.currency_id.compare_amounts(contract.monthly_amount, pricing['price_unit'])):
            raise UserError(_('El contrato domiciliado aplicado no coincide con el contratado.'))
        sequences = domiciliation.get('selected_installment_sequences') or []
        paid = contract.installment_ids.filtered(lambda item: item.sequence in sequences)
        if not sequences or len(paid) != len(sequences) or any(
            item.state != 'paid' or item.paid_pos_line_id != line or item.paid_pos_order_id != self
            for item in paid
        ):
            raise UserError(_('Las mensualidades seleccionadas no quedaron aplicadas al pago.'))
        if domiciliation.get('selection_mode') == 'initial' and contract.access_start_date != fields.Date.to_date(
            pricing['subscription_start_date']
        ):
            raise UserError(_('El inicio del contrato domiciliado no coincide con el contratado.'))
