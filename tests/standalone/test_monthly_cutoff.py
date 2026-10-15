"""Calendar regressions using pure primitives and the actual quotation methods."""

import calendar
from datetime import date, timedelta
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock

from test_subscription_contract import contract, method, POS, OPS


PRICING = 'witann_group_subscriptions_pos/models/pos_order_pricing.py'


def plan(interval=1, unit='month', *, aligned=False, domiciled=False):
    return SimpleNamespace(
        _fields={'billing_period_value', 'billing_period_unit'},
        billing_period_value=interval, billing_period_unit=unit,
        aligned=aligned, wgs_domiciliation_enabled=domiciled,
        ensure_one=lambda: None,
    )


def calculator(end=date(2026, 5, 20), cutoff=20, scheduled=()):
    source = SimpleNamespace(
        ensure_one=lambda: None, company_id=False, end_date=end,
        next_invoice_date=end + timedelta(days=1), wgs_monthly_cutoff_day=cutoff,
        _wgs_normalize_next_invoice_date_for_access=lambda next_date, end: next_date,
    )
    owner = SimpleNamespace(
        _wgs_should_align_plan_to_calendar_month=lambda p: p.aligned,
        _wgs_get_first_date_from_order=lambda order, names: next(
            (getattr(order, name) for name in names if getattr(order, name, False)), False,
        ),
        _wgs_pending_package_changes=lambda order: scheduled,
    )
    for name in (
        '_wgs_extract_interval_from_plan', '_wgs_uses_fixed_monthly_cutoff',
        '_wgs_get_sale_period_schedule', '_wgs_get_subscription_renewal_schedule',
        '_wgs_get_aligned_monthly_first_period_schedule',
    ):
        setattr(owner, name, MethodType(method(PRICING, name), owner))
    return owner, source


class MonthlyCutoffTests(unittest.TestCase):
    def test_new_monthly_ends_on_same_day_and_next_billing_is_exclusive(self):
        owner, _ = calculator()
        result = owner._wgs_get_sale_period_schedule(plan(), '2026-04-20')
        self.assertEqual(result, {
            'subscription_end_date': date(2026, 5, 20),
            'next_billing_date': date(2026, 5, 21), 'monthly_cutoff_day': 20,
        })

    def test_every_start_day_recovers_cutoff_for_twelve_renewals_including_leap_year(self):
        for year in (2026, 2027, 2028):
            for month in range(1, 13):
                for day in range(1, calendar.monthrange(year, month)[1] + 1):
                    start = date(year, month, day)
                    _, end, next_date = contract.period(start, 1, 'month', monthly_cutoff_day=day)
                    for _ in range(12):
                        self.assertEqual(end.day, min(day, calendar.monthrange(end.year, end.month)[1]))
                        self.assertEqual(next_date, end + timedelta(days=1))
                        old_end = end
                        actual_start, end, next_date = contract.period(
                            next_date, 1, 'month', monthly_cutoff_day=day, previous_end=old_end,
                        )
                        self.assertEqual(actual_start, old_end + timedelta(days=1))
                        self.assertGreater(end, old_end)

    def test_renewal_early_and_on_due_day_keeps_cutoff(self):
        owner, source = calculator()
        for today in ('2026-04-20', '2026-05-20', '2026-05-21'):
            result = owner._wgs_get_subscription_renewal_schedule(source, plan=plan(), today=today)
            self.assertEqual(result['renewal_anchor'], date(2026, 5, 21))
            self.assertEqual(result['subscription_end_date'], date(2026, 6, 20))
            self.assertEqual(result['next_billing_date'], date(2026, 6, 21))
            self.assertEqual(result['monthly_cutoff_day'], 20)
        self.assertEqual(source.end_date, date(2026, 5, 20))

    def test_short_month_recovers_original_cutoff(self):
        owner, source = calculator(date(2027, 2, 28), 31)
        result = owner._wgs_get_subscription_renewal_schedule(source, plan=plan(), today='2027-02-28')
        self.assertEqual(result['renewal_anchor'], date(2027, 3, 1))
        self.assertEqual(result['subscription_end_date'], date(2027, 3, 31))
        self.assertEqual(result['monthly_cutoff_day'], 31)

    def test_late_renewal_starts_today_without_changing_cut_day(self):
        owner, source = calculator()
        result = owner._wgs_get_subscription_renewal_schedule(source, plan=plan(), today='2026-05-25')
        self.assertEqual(result['renewal_anchor'], date(2026, 5, 25))
        self.assertEqual(result['subscription_end_date'], date(2026, 6, 20))
        self.assertEqual(result['monthly_cutoff_day'], 20)

    def test_legacy_paid_end_is_untouched_and_next_purchase_starts_new_calendar(self):
        owner, source = calculator(date(2026, 5, 19), 0)
        result = owner._wgs_get_subscription_renewal_schedule(source, plan=plan(), today='2026-05-01')
        self.assertEqual(result['renewal_anchor'], date(2026, 5, 20))
        self.assertEqual(result['subscription_end_date'], date(2026, 6, 20))
        self.assertEqual(result['monthly_cutoff_day'], 20)
        self.assertEqual(source.end_date, date(2026, 5, 19))
        self.assertEqual(source.wgs_monthly_cutoff_day, 0)

    def test_future_package_changes_use_last_paid_snapshot_cutoff(self):
        for cutoff, end, expected in (
            (31, date(2027, 4, 30), date(2027, 5, 31)),
            (0, date(2027, 4, 29), date(2027, 5, 30)),
        ):
            pending = SimpleNamespace(order_id=SimpleNamespace(
                _wgs_get_persisted_subscription_pricing_from_pos_line=lambda line: {
                    'subscription_end_date': end, 'monthly_cutoff_day': cutoff,
                },
            ))
            owner, source = calculator(date(2027, 2, 28), 31, [pending])
            result = owner._wgs_get_subscription_renewal_schedule(source, plan=plan(), today='2027-02-01')
            self.assertEqual(result['renewal_anchor'], end + timedelta(days=1))
            self.assertEqual(result['subscription_end_date'], expected)
            self.assertEqual(source.wgs_monthly_cutoff_day, 31)

    def test_aligned_renewal_keeps_month_end(self):
        owner, source = calculator()
        result = owner._wgs_get_subscription_renewal_schedule(source, plan=plan(aligned=True), today='2026-05-01')
        self.assertEqual(result['subscription_end_date'], date(2026, 5, 31))
        self.assertEqual(result['next_billing_date'], date(2026, 6, 1))
        self.assertEqual(result['monthly_cutoff_day'], 0)

    def test_other_terms_and_domiciliation_keep_existing_calendar(self):
        owner, _ = calculator()
        for target, expected in (
            (plan(1, 'day'), date(2026, 4, 20)),
            (plan(2, 'week'), date(2026, 5, 3)),
            (plan(6), date(2026, 10, 19)),
            (plan(1, 'year'), date(2027, 4, 19)),
            (plan(domiciled=True), date(2026, 5, 19)),
        ):
            result = owner._wgs_get_sale_period_schedule(target, '2026-04-20', monthly_cutoff_day=31)
            self.assertEqual(result['subscription_end_date'], expected)
            self.assertEqual(result['monthly_cutoff_day'], 0)

    def test_new_and_reenrollment_snapshots_include_cutoff(self):
        owner, _ = calculator()
        target = plan()
        owner._wgs_resolve_recurring_pricing = lambda *a, **kw: {
            'choice': {'plan_id': 9, 'price': 100, 'interval_value': 1, 'interval_unit': 'month'},
        }
        owner._wgs_resolve_plan_record = lambda *a, **kw: target
        owner._wgs_get_price_with_taxes_for_pos = lambda product, amount, **kw: amount
        owner.env = {'sale.order': False}
        product = SimpleNamespace(id=3, display_name='Monthly', ensure_one=lambda: None)
        build = method(PRICING, '_wgs_build_product_pricing_snapshot')
        for flow in ('new', 'reenroll'):
            result = build(owner, product, flow=flow, start_date='2026-04-20')
            self.assertEqual(result['subscription_end_date'], '2026-05-20')
            self.assertEqual(result['next_billing_date'], '2026-05-21')
            self.assertEqual(result['monthly_cutoff_day'], 20)
            self.assertEqual(result['charge_now'], 100)

    def test_metadata_sets_or_clears_cutoff_only_when_explicit(self):
        write = method('witann_group_subscriptions_pos/models/subscription_native_adapter.py', '_wgs_sync_subscription_metadata')
        owner, source = Mock(), Mock()
        write(owner, source)
        source.write.assert_not_called()
        for cutoff in (31, 0):
            write(owner, source, monthly_cutoff_day=cutoff)
            source.write.assert_called_with({'wgs_monthly_cutoff_day': cutoff})

    def test_legacy_source_revision_is_byte_compatible(self):
        owner, source = Mock(), Mock()
        source.id, source.company_id.id, source.partner_id.id = 7, 9, 12
        source.state, source.plan_id.id = 'sale', 3
        source._wgs_get_subscription_state_category.return_value = 'progress'
        source.wgs_effective_start_date = source.start_date = date(2026, 4, 20)
        source.end_date, source.next_invoice_date = date(2026, 5, 19), date(2026, 5, 20)
        source.participant_ids.ids = [12]
        source.order_line.sorted.return_value = []
        source.wgs_domiciliation_contract_id.id = False
        source.wgs_domiciliation_contract_id.installment_ids.sorted.return_value = []
        source.wgs_monthly_cutoff_day = 0
        revision = method(OPS, '_wgs_source_revision')
        expected = contract.fingerprint({
            'id': 7, 'company': 9, 'holder': 12, 'state': 'sale', 'subscription_state': 'active',
            'plan': 3, 'start': '2026-04-20', 'end': '2026-05-19', 'next': '2026-05-20',
            'participants': [12], 'lines': [], 'contract': False, 'installments': [], 'scheduled': [],
        })
        self.assertEqual(revision(owner, source), expected)
        source.wgs_monthly_cutoff_day = 20
        self.assertNotEqual(revision(owner, source), expected)

    def test_invalid_cutoff_and_overlapping_renewal_are_rejected(self):
        for cutoff in (-1, 32):
            with self.assertRaises(ValueError):
                contract.period('2026-04-20', 1, 'month', monthly_cutoff_day=cutoff)
        with self.assertRaises(ValueError):
            contract.period('2026-05-20', 1, 'month', monthly_cutoff_day=20, previous_end='2026-05-20')
        for interval, unit in ((1, 'day'), (6, 'month')):
            with self.assertRaises(ValueError):
                contract.period('2026-04-20', interval, unit, monthly_cutoff_day=20)


if __name__ == '__main__':
    unittest.main()
