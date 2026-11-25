"""Inclusive purchased calendars, historical replay and quotation integration."""

import calendar
from datetime import date, timedelta
from types import MethodType, SimpleNamespace
import unittest
from dateutil.relativedelta import relativedelta

from test_subscription_contract import contract, method, OPS
from test_monthly_cutoff import calculator, plan, PRICING


class InclusiveCalendarTests(unittest.TestCase):
    def test_requested_examples_and_leap_boundaries(self):
        for start, interval, unit, end, following in (
            ('2026-12-01', 1, 'month', '2026-12-31', '2027-01-01'),
            ('2026-12-02', 1, 'month', '2027-01-01', '2027-01-02'),
            ('2026-04-20', 1, 'month', '2026-05-19', '2026-05-20'),
            ('2027-01-31', 1, 'month', '2027-02-27', '2027-02-28'),
            ('2028-01-31', 1, 'month', '2028-02-28', '2028-02-29'),
            ('2026-12-01', 2, 'week', '2026-12-15', '2026-12-16'),
            ('2026-12-20', 2, 'week', '2027-01-03', '2027-01-04'),
            ('2026-12-01', 1, 'year', '2027-11-30', '2027-12-01'),
            ('2028-02-29', 1, 'year', '2029-02-27', '2029-02-28'),
            ('2026-12-01', 12, 'month', '2027-11-30', '2027-12-01'),
        ):
            with self.subTest(start=start, interval=interval, unit=unit):
                actual = contract.period(start, interval, unit, calendar_version=2)
                self.assertEqual(tuple(map(str, actual)), (start, end, following))

    def test_all_start_dates_and_successive_renewals_have_no_gaps_or_overlap(self):
        for year in (2026, 2027, 2028):
            for month in range(1, 13):
                for day in range(1, calendar.monthrange(year, month)[1] + 1):
                    for interval, unit, delta in (
                        (1, 'month', relativedelta(months=1)),
                        (2, 'week', timedelta(days=15)),
                        (1, 'year', relativedelta(years=1)),
                    ):
                        start = date(year, month, day)
                        for _ in range(3):
                            actual_start, end, following = contract.period(
                                start, interval, unit, calendar_version=2,
                            )
                            self.assertEqual(actual_start, start)
                            self.assertEqual(following, start + delta)
                            self.assertEqual(end + timedelta(days=1), following)
                            start = following

    def test_weekly_daily_alignment_and_legacy_quotes_do_not_change(self):
        self.assertEqual(contract.commercial_interval(1, 'week'), (1, 'week'))
        self.assertEqual(contract.commercial_interval(2, 'week'), (15, 'day'))
        self.assertEqual(contract.period('2026-12-01', 1, 'day', calendar_version=2)[1], date(2026, 12, 1))
        self.assertEqual(contract.period('2026-12-01', 1, 'week', calendar_version=2)[1], date(2026, 12, 7))
        self.assertEqual(contract.period('2026-12-15', 1, 'month', aligned=True, calendar_version=2)[1], date(2026, 12, 31))
        for version, interval, unit, cutoff, expected in (
            (1, 1, 'month', 1, '2027-01-01'),
            (1, 2, 'week', 0, '2026-12-14'),
            (2, 1, 'month', 0, '2026-12-31'),
            (2, 2, 'week', 0, '2026-12-15'),
        ):
            _, end, following = contract.period('2026-12-01', interval, unit,
                                               monthly_cutoff_day=cutoff, calendar_version=version)
            pricing = {
                'subscription_start_date': '2026-12-01', 'subscription_end_date': str(end),
                'next_billing_date': str(following), 'monthly_cutoff_day': cutoff,
                'period_contract': {'version': version, 'mode': 'term', 'start': '2026-12-01',
                                    'interval': interval, 'unit': unit, 'aligned': False,
                                    'cutoff': cutoff, 'previous_end': False},
            }
            self.assertEqual(str(end), expected)
            contract.validate_commercial_period(pricing)
            pricing['subscription_end_date'] = str(end + timedelta(days=1))
            with self.assertRaises(ValueError):
                contract.validate_commercial_period(pricing)

    def test_new_and_reenrollment_use_the_same_signed_calendar(self):
        owner, _ = calculator()
        owner.env = {'sale.order': False}
        owner._wgs_get_price_with_taxes_for_pos = lambda product, amount, **kw: amount
        product = SimpleNamespace(id=42, display_name='Purchased term', ensure_one=lambda: None)
        for target, expected in (
            (plan(), '2026-12-31'), (plan(2, 'week'), '2026-12-15'),
            (plan(1, 'year'), '2027-11-30'),
        ):
            owner._wgs_resolve_recurring_pricing = lambda *a, **kw: {'choice': {'plan_id': 9, 'price': 100}}
            owner._wgs_resolve_plan_record = lambda *a, **kw: target
            for flow in ('new', 'reenroll'):
                pricing = method(PRICING, '_wgs_build_product_pricing_snapshot')(
                    owner, product, flow=flow, start_date='2026-12-01',
                )
                pricing['period_contract'] = method(OPS, '_wgs_build_period_contract')(
                    owner, pricing, {'source_order': False, 'flow': flow}, target,
                )
                self.assertEqual(pricing['subscription_end_date'], expected)
                self.assertEqual(pricing['period_contract']['version'], 2)
                contract.validate_commercial_period(pricing)

    def test_renewals_start_after_paid_end_even_with_legacy_cutoff_or_late_payment(self):
        for target, expected in ((plan(), '2026-12-31'), (plan(2, 'week'), '2026-12-15'),
                                 (plan(1, 'year'), '2027-11-30')):
            owner, source = calculator(date(2026, 11, 30), 31)
            owner._wgs_get_subscription_business_today_for_pos = lambda **kw: date(2026, 12, 3)
            schedule = owner._wgs_get_subscription_renewal_schedule(source, plan=target)
            self.assertEqual(schedule['renewal_anchor'], date(2026, 12, 1))
            self.assertEqual(str(schedule['subscription_end_date']), expected)
            self.assertEqual(schedule['monthly_cutoff_day'], 0)
            pricing = {'subscription_start_date': str(schedule['renewal_anchor']),
                       'subscription_end_date': str(schedule['subscription_end_date']),
                       'next_billing_date': str(schedule['next_billing_date']), 'monthly_cutoff_day': 0}
            pricing['period_contract'] = method(OPS, '_wgs_build_period_contract')(
                owner, pricing, {'source_order': source, 'flow': 'renewal'}, target,
            )
            contract.validate_commercial_period(pricing)
            self.assertEqual(source.end_date, date(2026, 11, 30))
            self.assertEqual(source.wgs_monthly_cutoff_day, 31)

    def test_quincena_catalog_label_and_units_match_quoted_calendar(self):
        owner, _ = calculator()
        target = plan(2, 'week')
        target.id, target.display_name = 5, 'Quincena'
        pricing = SimpleNamespace(id=7)
        owner._wgs_extract_plan_record_from_pricing = lambda p: target
        owner._wgs_extract_price_from_pricing = lambda p: 450
        owner._wgs_extract_pricing_sequence = lambda p: 1
        owner._wgs_extract_plan_interval_label_from_pricing = MethodType(
            method(PRICING, '_wgs_extract_plan_interval_label_from_pricing'), owner,
        )
        candidate = method(PRICING, '_wgs_build_pricing_candidate')(owner, pricing)
        self.assertEqual((candidate['interval_value'], candidate['interval_unit']), (15, 'day'))
        self.assertEqual(candidate['interval_label'], '15 day')

    def test_version_two_cannot_reintroduce_legacy_cutoff(self):
        for kwargs in ({'monthly_cutoff_day': 20}, {'previous_end': '2026-11-30'},
                       {'calendar_version': 3}):
            with self.assertRaises(ValueError):
                contract.period('2026-12-01', 1, 'month', **{'calendar_version': 2, **kwargs})
