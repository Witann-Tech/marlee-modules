"""Regression of the actual 533.62 wallet / 533.63 catalog incident.

Runs production pricing/application methods with isolated records; ORM tests
remain the transaction/idempotency integration gate, not these doubles.
"""

from datetime import date, datetime
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock

from test_subscription_contract import method, UserError
from test_subscription_application import fixture, APPLICATION, Lines


PRICING = 'witann_group_subscriptions_pos/models/pos_order_pricing.py'


class Records(Lines):
    def filtered(self, predicate):
        return Records(item for item in self if predicate(item))

    def sorted(self, key):
        return Records(sorted(self, key=lambda item: getattr(item, key)))

    def invalidate_recordset(self):
        pass


def collection_fixture(*, historical_price=533.62, historical_discount=0, historical_qty=1):
    owner, line, sub, pricing = fixture()
    owner.id, line.id, sub.id, sub.name = 50, 51, 52, 'Historical subscription'
    owner.company_id = sub.company_id = SimpleNamespace(id=10)
    owner.partner_id = sub.partner_id = SimpleNamespace(id=7)
    owner.currency_id.id = 33
    sub.plan_id = SimpleNamespace(id=26, display_name='Domiciliados')
    sub.fiscal_position_id = False
    sub.order_line.price_unit = historical_price
    sub.order_line.discount = historical_discount
    sub.order_line.product_uom_qty = historical_qty
    empty = SimpleNamespace(id=False)
    installments = Records([
        SimpleNamespace(id=100, sequence=1, kind='initial_proration',
            period_start_date=date(2026, 9, 1), period_end_date=date(2026, 9, 30),
            due_date=date(2026, 9, 1), amount=533.62, state='paid', payment_source='pos',
            paid_pos_line_id=SimpleNamespace(id=9), paid_pos_order_id=SimpleNamespace(id=8),
            paid_at=datetime(2026, 9, 1)),
        SimpleNamespace(id=101, sequence=2, kind='regular',
            period_start_date=date(2026, 10, 1), period_end_date=date(2026, 10, 31),
            due_date=date(2026, 10, 1), amount=533.62, state='due', payment_source='pos',
            paid_pos_line_id=empty, paid_pos_order_id=empty, paid_at=False),
    ])
    contract = sub.wgs_domiciliation_contract_id = SimpleNamespace(
        id=137, state='active', subscription_id=sub, company_id=owner.company_id,
        partner_id=owner.partner_id, currency_id=sub.currency_id, product_id=line.product_id,
        plan_id=sub.plan_id, monthly_amount=533.62, access_start_date=date(2026, 9, 1),
        term_start_date=date(2026, 9, 1), term_end_date=date(2027, 8, 31), term_months=12,
        installment_ids=installments, flush_recordset=lambda: None, invalidate_recordset=lambda: None,
    )
    contract.wgs_get_renewal_quote = lambda **kw: {
        'contract_id': contract.id, 'selected_installment_sequences': [2],
        'amount_due_total': 533.62, 'installments': [], 'due_installment_count': 1,
    }
    owner._wgs_get_price_with_taxes_for_pos = lambda product, amount, **kw: round(amount * 1.16, 2)
    owner._wgs_get_domiciliation_installment_payloads_for_pos = lambda rows, **kw: rows
    owner._wgs_get_subscription_business_today_for_pos = lambda **kw: date(2026, 10, 28)
    owner._wgs_build_product_pricing_snapshot = Mock(side_effect=AssertionError('Live catalog must not be consulted'))
    owner._wgs_build_subscription_recurring_charge_payload = Mock(side_effect=AssertionError('Ordinary renewal must not reprice a wallet'))
    owner._wgs_source_contract = lambda s: {
        'id': s.id, 'plan': s.plan_id.id, 'end': str(s.end_date), 'participants': s.participant_ids.ids[:],
        'lines': [(i.product_id.id, i.product_uom_qty, i.price_unit, i.discount) for i in s.order_line],
        'installments': [(i.id, i.state) for i in contract.installment_ids],
    }
    for name in ('_wgs_domiciliation_collection_state', '_wgs_domiciliation_collection_revision',
                 '_wgs_validate_domiciliation_collection_quote'):
        setattr(owner, name, MethodType(method(APPLICATION, name), owner))
    line.wgs_subscription_flow, line.price_unit = 'renewal', 533.62
    pricing.update(price_unit=533.62, plan_id=26)
    quote = method(PRICING, '_wgs_build_domiciliation_collection_payload')(
        owner, sub, product=line.product_id, installment_sequences=[2],
    )
    pricing['snapshot'].update(quote)
    return owner, line, sub, pricing, contract


def apply_selected(owner, line, sub, pricing, contract):
    before = owner._wgs_domiciliation_collection_state(sub, selected_sequences=[2])
    paid = contract.installment_ids[1]
    paid.state, paid.paid_pos_line_id, paid.paid_pos_order_id = 'paid', line, owner
    paid.paid_at = datetime(2026, 10, 28)
    return before


class DomiciliationCollectionTests(unittest.TestCase):
    def test_quote_uses_wallet_price_and_full_october_even_if_catalog_is_different(self):
        owner, _line, _sub, pricing, _contract = collection_fixture()
        quote = pricing['snapshot']
        self.assertEqual(quote['recurring_price'], 533.62)
        self.assertEqual(quote['display_recurring_price'], 619)
        self.assertEqual(quote['ticket_charge_now'], 533.62)
        self.assertEqual(quote['display_charge_now'], 619)
        self.assertEqual(quote['subscription_start_date'], '2026-10-01')
        self.assertEqual(quote['subscription_end_date'], '2026-10-31')
        owner._wgs_build_product_pricing_snapshot.assert_not_called()
        owner._wgs_build_subscription_recurring_charge_payload.assert_not_called()

    def test_legacy_representation_is_preserved_not_rewritten_or_used_to_price_collection(self):
        for kwargs in ({}, {'historical_price': 0, 'historical_discount': 100}, {'historical_qty': 2}):
            with self.subTest(kwargs=kwargs):
                owner, line, sub, pricing, contract = collection_fixture(**kwargs)
                owner._wgs_validate_domiciliation_collection_quote(sub, pricing['snapshot'])
                before = apply_selected(owner, line, sub, pricing, contract)
                owner._wgs_assert_subscription_application(line, sub, pricing, before='old', collection_before=before)
                self.assertEqual(sub.order_line.price_unit, kwargs.get('historical_price', 533.62))
                self.assertEqual(contract.monthly_amount, 533.62)

    def test_queued_catalog_priced_quote_is_rejected_before_dispatch_not_silently_accepted(self):
        owner, _line, sub, pricing, _contract = collection_fixture()
        pricing['snapshot']['recurring_price'] = 533.63
        with self.assertRaises(UserError):
            owner._wgs_validate_domiciliation_collection_quote(sub, pricing['snapshot'])
        pricing['snapshot']['recurring_price'] = 533.62
        del pricing['snapshot']['domiciliation']['collection_revision']
        with self.assertRaises(UserError):
            owner._wgs_validate_domiciliation_collection_quote(sub, pricing['snapshot'])

    def test_term_amount_and_schedule_changes_invalidate_preflight_quote(self):
        for field, value in (('monthly_amount', 533.63), ('term_end_date', date(2028, 1, 1)),
                             ('term_months', 24)):
            owner, _line, sub, pricing, contract = collection_fixture()
            setattr(contract, field, value)
            with self.subTest(field=field), self.assertRaises(UserError):
                owner._wgs_validate_domiciliation_collection_quote(sub, pricing['snapshot'])

    def test_native_or_previous_payments_cannot_change_during_collection(self):
        for mutation in (
            lambda sub, c: setattr(sub.order_line[0], 'price_unit', 533.63),
            lambda sub, c: setattr(sub, 'end_date', date(2027, 1, 1)),
            lambda sub, c: setattr(c.installment_ids[0], 'paid_pos_line_id', SimpleNamespace(id=999)),
            lambda sub, c: setattr(c.installment_ids[0], 'amount', 100),
            lambda sub, c: setattr(c, 'monthly_amount', 534),
        ):
            owner, line, sub, pricing, contract = collection_fixture()
            before = apply_selected(owner, line, sub, pricing, contract)
            mutation(sub, contract)
            with self.assertRaises(UserError):
                owner._wgs_assert_subscription_application(line, sub, pricing, before='old', collection_before=before)

    def test_collection_requires_one_unit_and_correct_payment_link(self):
        for mutation in (
            lambda line, paid: setattr(line, 'qty', 2),
            lambda line, paid: setattr(paid, 'paid_pos_order_id', object()),
            lambda line, paid: setattr(paid, 'paid_pos_line_id', object()),
            lambda line, paid: setattr(paid, 'state', 'due'),
        ):
            owner, line, sub, pricing, contract = collection_fixture()
            before = apply_selected(owner, line, sub, pricing, contract)
            mutation(line, contract.installment_ids[1])
            with self.assertRaises(UserError):
                owner._wgs_assert_subscription_application(line, sub, pricing, before='old', collection_before=before)


if __name__ == '__main__':
    unittest.main()
