"""Actual activation methods with isolated collaborators, not an ORM substitute."""

from contextlib import nullcontext
from copy import deepcopy
from datetime import date, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock

from test_subscription_contract import contract, method, OPS, UserError


def recovery_fixture():
    values = {
        'id': 1905, 'company': 9, 'holder': 6681, 'state': 'sale',
        'subscription_state': 'active', 'plan': 15, 'start': '2026-09-15',
        'end': '2026-10-15', 'next': '2026-10-16', 'participants': [6681],
        'lines': [[3193, 1504, 1, 343.97, 0]], 'contract': False,
        'installments': [], 'scheduled': [], 'monthly_cutoff_day': 15,
    }
    expected = contract.fingerprint(values)
    source = Mock()
    owner = Mock()
    owner.with_context.return_value = owner
    source.with_env.return_value = source
    source.with_context.return_value = source
    owner._wgs_source_contract.side_effect = lambda record: deepcopy(values)
    owner._wgs_source_revision.side_effect = lambda record: contract.fingerprint(values)
    owner._wgs_is_automatic_inclusive_close.return_value = True
    owner._wgs_reactivate_subscription_order_for_pos.side_effect = lambda record: values.update(subscription_state='active')
    return owner, source, SimpleNamespace(wgs_activation_revision=expected), values


class Reasons(list):
    def __or__(self, other):
        return Reasons([*self, *other])

    def browse(self):
        return Reasons()


def close_fixture():
    root = SimpleNamespace(id=1, partner_id=SimpleNamespace(id=2))
    reason = object()
    owner = Mock()
    owner.env = MagicMock()
    owner.env.ref.side_effect = lambda xmlid, **kw: root if xmlid == 'base.user_root' else Reasons([reason])
    tracking = Mock()
    tracking.sudo.return_value = tracking
    tracking.search.return_value = object()
    owner.env.__getitem__.side_effect = lambda model: Reasons() if model == 'sale.order.close.reason' else tracking
    owner._wgs_get_subscription_business_date_from_datetime_for_pos.return_value = date(2026, 10, 15)
    source = SimpleNamespace(
        id=1905, state='sale', write_uid=root, close_reason_id=reason,
        write_date=datetime(2026, 10, 15, 20, 9), next_invoice_date=date(2026, 10, 16),
        end_date=date(2026, 10, 15), _wgs_get_subscription_state_category=lambda: 'closed',
    )
    line = SimpleNamespace(create_date=datetime(2026, 10, 15, 16, 14), wgs_application_date=date(2026, 10, 16))
    return owner, source, line, tracking


def activation_fixture():
    owner, order, line, source = (MagicMock() for _ in range(4))
    owner.env.cr.savepoint.return_value = nullcontext()
    owner.env['pos.order.line'].sudo().search.return_value = line
    line.order_id, line.wgs_subscription_source_id = order, source
    line.wgs_application_state, line.wgs_application_receipt = 'review', {}
    line.wgs_activation_attempts, line.wgs_activation_error = 0, False
    line.with_env.return_value = line
    def write(values):
        for key, value in values.items():
            setattr(line, key, value)
    line.write.side_effect = write
    order.state = 'paid'
    order.with_context.return_value = order
    order._wgs_prepare_paid_activation_source.return_value = False
    order._wgs_source_revision.return_value = 'after'
    apply = method(OPS, '_wgs_activate_package_change')
    apply.__globals__.update({
        'DeadlockDetected': type('DeadlockDetected', (Exception,), {}),
        'SerializationFailure': type('SerializationFailure', (Exception,), {}),
        '_logger': Mock(),
    })
    return owner, order, line, source, apply


class ActivationTests(unittest.TestCase):
    def test_missing_quoted_plan_is_rejected_during_preflight(self):
        owner = Mock()
        owner._wgs_verify_commercial_quote.return_value = {'pricing': {'plan_id': 17}}
        owner.env = MagicMock()
        owner.env['sale.subscription.plan'].browse().exists.return_value = False
        with self.assertRaisesRegex(UserError, 'antes de cobrar'):
            method(OPS, '_wgs_normalize_commercial_config')(
                owner, {'flow': 'renewal', 'pricing_snapshot': {}},
                partner_id=6681, company_id=9, check_source=False,
            )

    def test_paid_source_queue_is_finished_before_a_new_quote(self):
        owner = Mock()
        owner._wgs_get_subscription_business_today_for_pos.return_value = date(2026, 10, 19)
        line = Mock()
        owner._wgs_pending_package_changes.return_value.filtered.return_value = [line]
        line.order_id._wgs_activate_package_change.return_value = True
        method(OPS, '_wgs_settle_due_source_changes')(owner, Mock())
        line.order_id._wgs_activate_package_change.assert_called_once_with(line)

    def test_failed_due_purchase_prevents_another_charge_not_another_subscription(self):
        owner = Mock()
        owner._wgs_get_subscription_business_today_for_pos.return_value = date(2026, 10, 19)
        line = Mock()
        owner._wgs_pending_package_changes.return_value.filtered.return_value = [line]
        line.order_id._wgs_activate_package_change.return_value = False
        line.order_id.pos_reference = '2648-8-000088'
        with self.assertRaisesRegex(UserError, 'no vuelvas a cobrar'):
            method(OPS, '_wgs_settle_due_source_changes')(owner, Mock())
        owner._wgs_dispatch_subscription_operation.assert_not_called()

    def test_unchanged_paid_source_needs_no_recovery_or_new_payment(self):
        owner, source, line, _values = recovery_fixture()
        self.assertFalse(method(OPS, '_wgs_prepare_paid_activation_source')(owner, source, line))
        owner._wgs_reactivate_subscription_order_for_pos.assert_not_called()
        owner._wgs_is_automatic_inclusive_close.assert_not_called()

    def test_exact_state_only_auto_close_recovers_on_first_attempt(self):
        owner, source, line, values = recovery_fixture()
        values['subscription_state'] = '6_churn'
        self.assertTrue(method(OPS, '_wgs_prepare_paid_activation_source')(owner, source, line))
        self.assertEqual(values['subscription_state'], 'active')
        owner._wgs_reactivate_subscription_order_for_pos.assert_called_once()
        source.write.assert_called_once_with({'close_reason_id': False})

    def test_other_commercial_differences_are_never_silently_overwritten(self):
        mutations = {
            'holder': 9000, 'company': 10, 'plan': 17, 'end': '2026-10-14',
            'participants': [6681, 9000], 'lines': [[3193, 1553, 1, 215.52, 0]],
            'monthly_cutoff_day': 20,
        }
        for key, value in mutations.items():
            with self.subTest(key=key):
                owner, source, line, values = recovery_fixture()
                values.update(subscription_state='6_churn')
                values[key] = value
                with self.assertRaises(UserError):
                    method(OPS, '_wgs_prepare_paid_activation_source')(owner, source, line)
                owner._wgs_reactivate_subscription_order_for_pos.assert_not_called()

    def test_manual_close_without_audit_evidence_is_not_reopened(self):
        owner, source, line, values = recovery_fixture()
        values['subscription_state'] = '6_churn'
        owner._wgs_is_automatic_inclusive_close.return_value = False
        with self.assertRaises(UserError):
            method(OPS, '_wgs_prepare_paid_activation_source')(owner, source, line)
        owner._wgs_reactivate_subscription_order_for_pos.assert_not_called()

    def test_recovery_checks_postcondition_not_only_prepared_values(self):
        owner, source, line, values = recovery_fixture()
        values['subscription_state'] = '6_churn'
        owner._wgs_reactivate_subscription_order_for_pos.side_effect = None
        with self.assertRaises(UserError):
            method(OPS, '_wgs_prepare_paid_activation_source')(owner, source, line)

    def test_auto_close_requires_bot_reason_date_and_state_tracking(self):
        owner, source, line, tracking = close_fixture()
        self.assertTrue(method(OPS, '_wgs_is_automatic_inclusive_close')(owner, source, line))
        domain = tracking.search.call_args.args[0]
        self.assertIn(('mail_message_id.res_id', '=', 1905), domain)
        self.assertIn(('mail_message_id.author_id', '=', 2), domain)
        self.assertIn(('field_id.name', '=', 'subscription_state'), domain)
        tracking.search.return_value = False
        self.assertFalse(method(OPS, '_wgs_is_automatic_inclusive_close')(owner, source, line))

    def test_manual_actor_unknown_reason_later_close_and_later_sale_are_excluded(self):
        for mutation in ('actor', 'reason', 'date', 'sale', 'next'):
            with self.subTest(mutation=mutation):
                owner, source, line, tracking = close_fixture()
                if mutation == 'actor': source.write_uid = object()
                if mutation == 'reason': source.close_reason_id = object()
                if mutation == 'date': source.end_date = date(2026, 10, 14)
                if mutation == 'sale': line.create_date = datetime(2026, 10, 16)
                if mutation == 'next': source.next_invoice_date = date(2026, 11, 16)
                self.assertFalse(method(OPS, '_wgs_is_automatic_inclusive_close')(owner, source, line))
                tracking.search.assert_not_called()

    def test_legacy_review_is_applied_without_human_intervention(self):
        owner, order, line, _source, apply = activation_fixture()
        self.assertTrue(apply(owner, line))
        self.assertEqual(line.wgs_application_state, 'applied')
        self.assertFalse(line.wgs_activation_error)
        order._wgs_apply_subscription_operation.assert_called_once()
        order._wgs_finalize_paid_access.assert_called_once()
        self.assertFalse(apply(owner, line))
        order._wgs_apply_subscription_operation.assert_called_once()

    def test_transient_failure_retries_automatically_instead_of_quarantining(self):
        owner, order, line, _source, apply = activation_fixture()
        order._wgs_apply_subscription_operation.side_effect = UserError('Temporary native failure')
        self.assertFalse(apply(owner, line))
        self.assertEqual(line.wgs_application_state, 'scheduled')
        self.assertEqual(line.wgs_activation_attempts, 1)
        self.assertEqual(line.wgs_activation_retry_at, datetime(2026, 10, 14, 12, 15))
        self.assertEqual(line.wgs_activation_error, 'Temporary native failure')
        order._wgs_finalize_paid_access.assert_not_called()
        order._wgs_apply_subscription_operation.side_effect = None
        self.assertTrue(apply(owner, line))
        self.assertEqual(line.wgs_application_state, 'applied')
        self.assertFalse(line.wgs_activation_error)
        self.assertFalse(line.wgs_activation_retry_at)

    def test_native_transaction_conflicts_are_propagated_not_hidden(self):
        owner, order, line, _source, apply = activation_fixture()
        conflict = apply.__globals__['SerializationFailure']
        order._wgs_apply_subscription_operation.side_effect = conflict('retry Odoo transaction')
        with self.assertRaises(conflict):
            apply(owner, line)
        line.write.assert_not_called()

    def test_unpaid_cancelled_and_out_of_order_operations_cannot_activate(self):
        for state in ('draft', 'cancelled', 'later'):
            with self.subTest(state=state):
                owner, order, line, _source, apply = activation_fixture()
                if state == 'draft': order.state = 'draft'
                if state == 'cancelled': line.wgs_application_state = 'cancelled'
                if state == 'later': owner.env['pos.order.line'].sudo().search.return_value = object()
                self.assertFalse(apply(owner, line))
                order._wgs_apply_subscription_operation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
