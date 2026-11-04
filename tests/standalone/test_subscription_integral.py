"""Review regressions using actual validators, without claiming ORM coverage."""

from contextlib import nullcontext
from copy import deepcopy
from datetime import date
import json
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock

from test_subscription_contract import contract, method, OPS, POS, UserError
from test_subscription_application import fixture
from test_subscription_activation import activation_fixture, recovery_fixture
from test_monthly_cutoff import calculator, plan


class IntegralCommercialTests(unittest.TestCase):
    def test_sealing_rejects_monthly_quote_with_quarter_duration(self):
        owner, _source = calculator()
        owner.env = MagicMock()
        owner.env['sale.subscription.plan'].browse().exists.return_value = plan()
        owner._wgs_find_plan_record_by_id = lambda value: plan()
        owner._wgs_build_period_contract = MethodType(method(OPS, '_wgs_build_period_contract'), owner)
        owner._wgs_quote_signature = Mock(return_value='local-test-signature')
        owner._wgs_source_revision = lambda *args, **kw: False
        pricing = {
            'plan_id': 9, 'subscription_start_date': '2026-10-14',
            'subscription_end_date': '2027-01-14', 'next_billing_date': '2027-01-15', 'monthly_cutoff_day': 14,
        }
        request = {'source_order': False, 'product': SimpleNamespace(id=20, max_participants_total=1),
                   'partner': SimpleNamespace(id=8), 'flow': 'new'}
        with self.assertRaises(UserError):
            method(OPS, '_wgs_seal_pricing_payload')(owner, pricing, request)
        owner._wgs_quote_signature.assert_not_called()
        pricing.update(subscription_end_date='2026-11-14', next_billing_date='2026-11-15')
        result = method(OPS, '_wgs_seal_pricing_payload')(owner, pricing, request)
        self.assertEqual(result['period_contract']['interval'], 1)
        self.assertEqual(result['commercial_quote']['payload']['pricing']['period_contract'], result['period_contract'])

    def test_independent_period_check_rejects_matching_wrong_native_dates(self):
        owner, line, subscription, pricing = fixture()
        subscription.end_date = pricing['subscription_end_date'] = date(2027, 1, 14)
        subscription.next_invoice_date = pricing['next_billing_date'] = date(2027, 1, 15)
        pricing['snapshot'].update(subscription_end_date='2027-01-14', next_billing_date='2027-01-15')
        with self.assertRaisesRegex(UserError, 'plazo comprado'):
            owner._wgs_assert_subscription_application(line, subscription, pricing, before=False)

    def test_even_a_valid_signature_cannot_authorize_a_wrong_term(self):
        _owner, _line, _subscription, pricing = fixture()
        snapshot = pricing['snapshot']
        snapshot.update(subscription_end_date='2027-01-14', next_billing_date='2027-01-15')
        owner = SimpleNamespace(env={'ir.config_parameter': Mock()})
        owner.env['ir.config_parameter'].sudo.return_value.get_param.return_value = 'isolated-test-secret'
        owner._wgs_quote_signature = MethodType(method(OPS, '_wgs_quote_signature'), owner)
        payload = {'rules_version': 1, 'product_id': 20, 'partner_id': 8, 'company_id': 9,
                   'flow': 'new', 'source_subscription_id': False, 'pricing': snapshot}
        signed = {'commercial_quote': {'payload': payload, 'signature': owner._wgs_quote_signature(payload)}}
        with self.assertRaisesRegex(UserError, 'plazo contratado'):
            method(OPS, '_wgs_verify_commercial_quote')(
                owner, signed, product_id=20, partner_id=8, company_id=9, flow='new', source_id=False,
            )

    def test_cancelled_closed_draft_and_non_subscription_cannot_be_applied(self):
        for mutation in ('cancel', 'churn', 'draft', 'renew_state', 'not_subscription'):
            owner, line, subscription, pricing = fixture()
            if mutation in ('cancel', 'draft'):
                subscription.state = mutation
            elif mutation == 'churn':
                subscription._wgs_get_subscription_state_category = lambda: 'closed'
            elif mutation == 'renew_state':
                subscription._wgs_get_subscription_state_category = lambda: 'renew'
            else:
                subscription.is_subscription = False
            with self.subTest(mutation=mutation), self.assertRaisesRegex(UserError, 'operable'):
                owner._wgs_assert_subscription_application(line, subscription, pricing, before=False)

    def test_frozen_calendar_handles_daily_quarter_annual_leap_and_alignment(self):
        for interval, unit, cutoff, aligned, start, end, following in (
            (1, 'day', 0, False, '2026-10-14', '2026-10-14', False),
            (3, 'month', 0, False, '2026-10-14', '2027-01-13', '2027-01-14'),
            (1, 'year', 0, False, '2026-10-14', '2027-10-13', '2027-10-14'),
            (1, 'month', 31, False, '2027-01-31', '2027-02-28', '2027-03-01'),
            (12, 'month', 0, True, '2026-10-14', '2026-10-31', '2026-11-01'),
        ):
            pricing = dict(subscription_start_date=start, subscription_end_date=end, next_billing_date=following,
                           monthly_cutoff_day=cutoff, period_contract={
                'version': 1, 'mode': 'term', 'start': start, 'interval': interval, 'unit': unit,
                'aligned': aligned, 'cutoff': cutoff, 'previous_end': False,
            })
            contract.validate_commercial_period(pricing)
            pricing['subscription_end_date'] = '2028-01-01'
            with self.assertRaises(ValueError):
                contract.validate_commercial_period(pricing)

    def test_renewal_contract_continues_31_cutoff_after_short_month(self):
        owner, source = calculator(date(2027, 2, 28), 31)
        owner._wgs_get_subscription_business_today_for_pos = lambda **kw: date(2027, 2, 28)
        schedule = owner._wgs_get_subscription_renewal_schedule(source, plan=plan())
        pricing = dict(subscription_start_date=str(schedule['renewal_anchor']),
                       subscription_end_date=str(schedule['subscription_end_date']),
                       next_billing_date=str(schedule['next_billing_date']), monthly_cutoff_day=31)
        pricing['period_contract'] = method(OPS, '_wgs_build_period_contract')(
            owner, pricing, {'source_order': source, 'flow': 'renewal'}, plan(),
        )
        contract.validate_commercial_period(pricing)
        self.assertEqual(pricing['period_contract']['previous_end'], '2027-02-28')

    def test_paid_future_participants_are_independent_of_current_participants(self):
        owner, source, line, values = recovery_fixture()
        line.wgs_activation_contract = deepcopy(values)
        values['participants'] = [6681, 9000]
        self.assertFalse(method(OPS, '_wgs_prepare_paid_activation_source')(owner, source, line))
        owner._wgs_reactivate_subscription_order_for_pos.assert_not_called()
        self.assertEqual(line.wgs_activation_contract['participants'], [6681])
        values['plan'] = 999
        with self.assertRaises(UserError):
            method(OPS, '_wgs_prepare_paid_activation_source')(owner, source, line)

    def test_invalid_frozen_revision_and_legacy_drift_are_not_rebased(self):
        for frozen in (False, {'participants': [6681]}):
            owner, source, line, values = recovery_fixture()
            line.wgs_activation_contract = frozen
            values['participants'] = [6681, 9000]
            with self.assertRaises(UserError):
                method(OPS, '_wgs_prepare_paid_activation_source')(owner, source, line)

    def test_participant_edit_survives_json_roundtrip_of_native_line_tuples(self):
        owner, source, line, values = recovery_fixture()
        values['lines'] = [tuple(values['lines'][0])]
        line.wgs_activation_revision = contract.fingerprint(values)
        line.wgs_activation_contract = json.loads(contract.canonical_json(values))
        values['participants'] = [6681, 9000]
        self.assertFalse(method(OPS, '_wgs_prepare_paid_activation_source')(owner, source, line))

    def test_holder_reenrollment_checks_other_active_or_future_contracts(self):
        class Contracts(list):
            def __sub__(self, other):
                return Contracts(item for item in self if item != other)

        buyer = SimpleNamespace(ensure_one=lambda: None)
        source = SimpleNamespace(partner_id=buyer, participant_ids=[buyer], state='sale',
                                 company_id=False, ensure_one=lambda: None)
        owner = Mock()
        for state in ('progress', 'future'):
            candidate = SimpleNamespace(display_name='Another paid contract',
                _wgs_subscription_operation_policy_for_pos=lambda: {'can_renew': state == 'progress', 'state_key': state})
            owner._wgs_find_subscription_history_for_partner.return_value = Contracts([source, candidate])
            with self.assertRaises(UserError):
                method(POS, '_wgs_reenrollment_requires_new_contract')(owner, source, buyer)
        owner._wgs_find_subscription_history_for_partner.return_value = Contracts([source])
        self.assertFalse(method(POS, '_wgs_reenrollment_requires_new_contract')(owner, source, buyer))

    def test_two_new_memberships_are_rejected_before_native_payment(self):
        owner = MagicMock()
        owner._wgs_to_int.side_effect = lambda value: int(value or 0)
        products = owner.env['product.product'].browse().exists.return_value
        products.filtered.side_effect = lambda predicate: SimpleNamespace(ids=[20, 21] if predicate == 'recurring_invoice' else [])
        lines = [dict(uuid=str(i), product_id=i, qty=1, price_unit=100, discount=0) for i in (20, 21)]
        configs = [dict(line_uuid=str(i), product_id=i, quantity=1, flow='new',
                        pricing_snapshot={'ticket_charge_now': 100}) for i in (20, 21)]
        with self.assertRaisesRegex(UserError, 'nueva membresia'):
            method(OPS, '_wgs_validate_ticket_memberships')(owner, lines, configs)
        method(OPS, '_wgs_validate_ticket_memberships')(owner, lines[:1], configs[:1])
        configs[1].update(flow='pending_charge')
        method(OPS, '_wgs_validate_ticket_memberships')(owner, lines, configs)

    def test_access_pending_requires_verified_projection_not_only_no_exception(self):
        for result in (None, {'checked': 1, 'issues': [{'reason': 'enabled_projection_missing'}]},
                       {'checked': 0, 'issues': []}, {'checked': 1, 'issues': []}):
            owner, sources = Mock(), Mock()
            owner.env.cr.savepoint.return_value = nullcontext()
            sources._wgs_get_access_related_partner_ids.return_value = {10}
            sources.with_context.return_value = sources
            sources._wgs_sync_access_control_people.return_value = result
            method(OPS, '_wgs_finalize_paid_access')(owner, sources, {10})
            cleared = any(call.args[0].get('wgs_access_sync_pending') is False for call in owner.write.call_args_list)
            self.assertEqual(cleared, result == {'checked': 1, 'issues': []})

    def test_allocator_versions_one_shared_row_before_reading_free_ids(self):
        owner = Mock()
        owner.env.ref.return_value.id = 42
        owner.env.cr.fetchone.return_value = (42,)
        method('access_control_api/models/access_person.py', '_lock_global_user_id_allocator')(owner)
        sql, params = owner.env.cr.execute.call_args.args
        self.assertIn('UPDATE ir_config_parameter SET value = value', sql)
        self.assertEqual(params, [42])
        owner.env.cr.commit.assert_not_called()
        owner.env.cr.rollback.assert_not_called()

    def test_persistent_activation_failure_has_bounded_backoff_not_a_terminal_review(self):
        owner, order, line, _source, apply = activation_fixture()
        line.wgs_activation_attempts = 100
        order._wgs_apply_subscription_operation.side_effect = UserError('Persistent failure')
        self.assertFalse(apply(owner, line))
        self.assertEqual(line.wgs_application_state, 'scheduled')
        self.assertEqual(line.wgs_activation_retry_at.hour, 18)
        self.assertEqual(line.wgs_activation_attempts, 101)

    def test_directory_none_count_is_derived_without_classifying_unrelated_contacts(self):
        owner = MagicMock()
        partner = owner._wgs_partner_model_for_pos.return_value
        partner.search_count.side_effect = [100, 20]
        owner._get_partner_directory_summary_state_counts_for_pos.return_value = {
            1: 'progress', 2: 'closed', 3: 'manual_access', 4: 'none',
        }
        result = method('witann_group_subscriptions_pos/models/sale_order.py', 'get_partner_directory_summary_for_pos')(owner)
        self.assertEqual(result['none'], 97)
        self.assertEqual(result['total'], 100)
        self.assertEqual(result['cancel'], 1)
        self.assertEqual(result['closed'], 1)
        partner.search.assert_not_called()


if __name__ == '__main__':
    unittest.main()
