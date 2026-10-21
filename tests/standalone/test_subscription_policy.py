"""Shared commercial decisions and native boundaries, without an Odoo server."""

import ast
from datetime import date
from pathlib import Path
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock

from test_subscription_contract import method, POS, UserError
from test_subscription_application import fixture


BASE = 'witann_group_subscriptions/models/sale_order.py'
SALE = 'witann_group_subscriptions_pos/models/sale_order.py'


def source(*, state='progress', start=date(2026, 9, 19), end=date(2026, 10, 19),
           next_date=date(2026, 10, 20), deadline=None, replacement=False, access='enabled'):
    item = SimpleNamespace(
        id=1, state='sale', ensure_one=lambda: None, company_id=1, wgs_domiciliation_contract_id=False,
        _wgs_has_replacement_subscription_for_pos=lambda: replacement,
        _get_native_subscription_state_info_for_pos=lambda: (state, state),
        _classify_subscription_access_state_for_pos=lambda: access,
        _wgs_get_subscription_access_period=lambda: {
            'start_date': start, 'valid_until': end, 'next_invoice_date': next_date,
        },
        _wgs_get_subscription_auto_close_deadline_from_order=lambda **kw: deadline,
        _wgs_subscription_business_today_for_pos=lambda **kw: date(2026, 10, 20),
    )
    item._wgs_subscription_operation_policy_for_pos = MethodType(
        method(SALE, '_wgs_subscription_operation_policy_for_pos'), item,
    )
    return item


class SharedPolicyTests(unittest.TestCase):
    def test_grace_expiration_allows_reenrollment_before_native_cron_runs(self):
        item = source(deadline=date(2026, 10, 20), access=False)
        policy = item._wgs_subscription_operation_policy_for_pos()
        self.assertEqual(policy['state_key'], 'closed')
        self.assertTrue(method(POS, '_wgs_is_subscription_order_closed_for_reenroll')(None, item))
        self.assertFalse(method(POS, '_wgs_is_subscription_order_renewable_for_pos')(None, item))
        self.assertFalse(method(POS, '_wgs_is_subscription_order_active_for_upsell')(None, item))

    def test_last_inclusive_day_renewable_then_expired_within_grace(self):
        item = source(deadline=date(2026, 10, 25))
        last = item._wgs_subscription_operation_policy_for_pos(today=date(2026, 10, 19))
        self.assertTrue(last['can_renew'])
        self.assertTrue(last['can_upsale'])
        expired = item._wgs_subscription_operation_policy_for_pos()
        self.assertEqual(expired['state_key'], 'renew')
        self.assertTrue(expired['can_renew'])
        self.assertFalse(expired['can_reenroll'])
        self.assertFalse(expired['can_upsale'])

    def test_future_manual_closed_and_replaced_have_explicit_distinct_actions(self):
        for item, expected in (
            (source(start=date(2026, 11, 1)), (False, False)),
            (source(state='closed'), (False, True)),
            (source(state='closed', start=date(2026, 11, 1)), (False, True)),
            (source(replacement=True), (False, False)),
        ):
            result = item._wgs_subscription_operation_policy_for_pos()
            self.assertEqual((result['can_renew'], result['can_reenroll']), expected)

    def test_domiciliation_uses_installments_not_native_accounting_state(self):
        item = source(state='closed')
        item.wgs_domiciliation_contract_id = SimpleNamespace(
            state='active', wgs_get_operational_status=lambda **kw: {
                'state_key': 'renew', 'access_state': 'suspended', 'can_renew': True,
            },
        )
        result = item._wgs_subscription_operation_policy_for_pos()
        self.assertTrue(result['can_renew'])
        self.assertFalse(result['can_reenroll'])
        self.assertFalse(result['can_upsale'])

    def test_directory_can_reuse_batch_replacements_but_payment_checks_fresh(self):
        item = source()
        item._wgs_has_replacement_subscription_for_pos = Mock(return_value=True)
        item._wgs_subscription_operation_policy_for_pos(replacement_status={1: False})
        item._wgs_has_replacement_subscription_for_pos.assert_not_called()
        self.assertFalse(item._wgs_subscription_operation_policy_for_pos()['can_renew'])
        item._wgs_has_replacement_subscription_for_pos.assert_called_once_with()

    def test_paid_activation_is_not_rejected_by_today_purchase_eligibility(self):
        class ReachedApplication(Exception):
            pass
        owner, line, subscription = Mock(), Mock(), Mock()
        line.wgs_subscription_source_id = subscription
        subscription.exists.return_value = subscription
        subscription.wgs_domiciliation_contract_id = False
        subscription._wgs_get_subscription_state_category.return_value = 'progress'
        owner._wgs_is_subscription_order_renewable_for_pos.return_value = False
        subscription.order_line.filtered.side_effect = ReachedApplication()
        renew = method(POS, '_wgs_process_subscription_renewal_line')
        with self.assertRaises(UserError):
            renew(owner, line)
        with self.assertRaises(ReachedApplication):
            renew(owner, line, activation=True)
        subscription._wgs_get_subscription_state_category.return_value = 'closed'
        with self.assertRaises(UserError):
            renew(owner, line, activation=True)

    def test_native_close_uses_mutating_api_and_preserves_paid_history(self):
        item = Mock()
        item.end_date = date(2026, 11, 19)
        item.with_context.return_value = item
        def native_close():
            item.end_date = date(2026, 10, 18)
        item.set_close.side_effect = native_close
        item._wgs_get_subscription_state_category.return_value = 'closed'
        method(BASE, '_wgs_close_subscription_commercially')(item, origin='upsale')
        item.set_close.assert_called_once_with()
        item.action_close.assert_not_called()
        item.write.assert_called_once_with({'end_date': date(2026, 11, 19)})

    def test_close_failure_cannot_be_reported_as_success(self):
        item = Mock()
        item.with_context.return_value = item
        item._wgs_get_subscription_state_category.return_value = 'progress'
        with self.assertRaises(UserError):
            method(BASE, '_wgs_close_subscription_commercially')(item, origin='upsale')
        item.write.assert_not_called()

    def test_cancel_domiciliation_keeps_all_installments(self):
        item = Mock()
        contracts = item.mapped.return_value.filtered.return_value
        method(BASE, '_wgs_cancel_domiciliation_on_explicit_close')(item)
        contracts.write.assert_called_once_with({'state': 'cancelled'})
        contracts.unlink.assert_not_called()

    def test_native_close_cancels_only_explicit_commercial_closures(self):
        tree = ast.parse((Path(__file__).resolve().parents[2] / BASE).read_text())
        close = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'SaleOrder')
        close.body = [node for node in close.body if isinstance(node, ast.FunctionDef) and node.name == 'set_close']
        close.bases = [ast.Name(id='Native', ctx=ast.Load())]
        class Native:
            def set_close(self, **kw):
                self.native_calls += 1
                return True
        namespace = {'Native': Native}
        ast.fix_missing_locations(close)
        exec(compile(ast.Module(body=[close], type_ignores=[]), BASE, 'exec'), namespace)
        for context, renew, expected in (
            ({}, False, 1), ({}, True, 0),
            ({'wgs_native_subscription_lifecycle': True}, False, 0),
            ({'wgs_subscription_close_origin': 'auto_close'}, False, 0),
            ({'wgs_subscription_close_origin': 'upsale'}, False, 1),
        ):
            item = namespace['SaleOrder']()
            item.env = SimpleNamespace(context=context)
            item.native_calls = 0
            item._wgs_cancel_domiciliation_on_explicit_close = Mock()
            item.set_close(renew=renew)
            self.assertEqual(item.native_calls, 1)
            self.assertEqual(item._wgs_cancel_domiciliation_on_explicit_close.call_count, expected)

    def test_optional_dates_have_the_real_odoo_none_semantics(self):
        for expected in (False, None, ''):
            owner, line, subscription, pricing = fixture()
            subscription.end_date = pricing['subscription_end_date'] = date(2026, 10, 14)
            subscription.next_invoice_date = False
            subscription.wgs_monthly_cutoff_day = pricing['monthly_cutoff_day'] = 0
            pricing['next_billing_date'] = expected
            owner._wgs_assert_subscription_application(line, subscription, pricing, before=False)
        pricing['next_billing_date'] = date(2026, 10, 15)
        with self.assertRaises(UserError):
            owner._wgs_assert_subscription_application(line, subscription, pricing, before=False)

    def test_upsale_postcondition_rejects_open_source(self):
        owner, line, subscription, pricing = fixture()
        line.wgs_subscription_flow = 'upsale'
        old = SimpleNamespace(_wgs_get_subscription_state_category=lambda: 'progress')
        line.wgs_subscription_source_id = old
        with self.assertRaises(UserError):
            owner._wgs_assert_subscription_application(line, subscription, pricing, before=False)
        old._wgs_get_subscription_state_category = lambda: 'closed'
        owner._wgs_assert_subscription_application(line, subscription, pricing, before=False)

    def test_upsale_display_comes_from_the_exact_taxed_ticket_price(self):
        owner, product, old, plan = Mock(), Mock(), Mock(), Mock()
        owner._wgs_resolve_recurring_pricing.return_value = {'choice': {'price': 1206.03}}
        owner._wgs_resolve_plan_record.return_value = plan
        owner._wgs_uses_fixed_monthly_cutoff.return_value = False
        old.exists.return_value = old
        owner._wgs_get_upsale_source_recurring_amount.side_effect = lambda *a, **kw: 799 if kw else 688.79
        owner._wgs_get_upsale_schedule_from_source.return_value = {}
        owner._wgs_get_price_with_taxes_for_pos.side_effect = lambda product, price, **kw: round(price * 1.16, 2)
        result = method('witann_group_subscriptions_pos/models/pos_order_pricing.py',
                        '_wgs_build_product_pricing_snapshot')(
            owner, product, source_order=old, include_credit=True, flow='upsale',
        )
        self.assertEqual(result['ticket_charge_now'], 517.24)
        self.assertEqual(result['display_charge_now'], 600)
        self.assertEqual(round(result['display_price_unit'] - result['display_credit_amount'], 2), 599.99)
