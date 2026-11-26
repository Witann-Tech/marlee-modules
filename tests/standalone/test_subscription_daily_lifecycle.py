"""Daily expiry shares the real close deadline with directory/checkout policy."""

from datetime import date, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from test_subscription_contract import method, OPS, UserError
from test_subscription_policy import source, BASE


close_deadline = method(BASE, '_wgs_get_subscription_auto_close_deadline')


def deadline(end, *, daily=True, grace=0):
    plan = SimpleNamespace(wgs_single_day_plan=daily)
    owner = SimpleNamespace(
        _fields={'plan_id'}, plan_id=plan,
        _wgs_get_subscription_plan_from_line=lambda line: plan,
        _wgs_get_subscription_plan_auto_close_days=lambda plan: grace,
    )
    return close_deadline(owner, next_invoice_date=end + timedelta(days=1))


class DailyLifecycleTests(unittest.TestCase):
    def test_all_calendar_days_expire_without_grace_but_not_on_the_last_day(self):
        start = date(2026, 1, 1)
        item = source()
        item._wgs_get_subscription_access_period = lambda: {
            'start_date': end, 'valid_until': end, 'next_invoice_date': close,
        }
        item._wgs_get_subscription_auto_close_deadline_from_order = lambda **kw: close
        for offset in range((date(2029, 1, 1) - start).days):
            end = start + timedelta(days=offset)
            for grace in (0, 3, 30):
                with self.subTest(end=end, grace=grace):
                    close = deadline(end, grace=grace)
                    self.assertEqual(close, end + timedelta(days=1))
                    self.assertTrue(item._wgs_subscription_operation_policy_for_pos(today=end)['can_renew'])
                    for gap in (1, 2, 7, 30, 365):
                        day = end + timedelta(days=gap)
                        policy = item._wgs_subscription_operation_policy_for_pos(today=day)
                        self.assertFalse(policy['can_renew'])
                        self.assertTrue(policy['can_reenroll'])

    def test_zero_still_disables_ordinary_auto_close(self):
        end = date(2026, 11, 25)
        self.assertFalse(deadline(end, daily=False, grace=0))
        for grace in (1, 3, 15):
            self.assertEqual(deadline(end, daily=False, grace=grace), end + timedelta(days=grace + 1))

    def test_replacement_manual_close_future_and_wallet_keep_their_precedence(self):
        end = date(2026, 11, 25)
        close = deadline(end)
        for options, expected in (
            ({'replacement': True}, (False, False)),
            ({'state': 'closed'}, (False, True)),
            ({'start': date(2026, 12, 1)}, (False, False)),
        ):
            item = source(end=end, next_date=close, deadline=close, **options)
            policy = item._wgs_subscription_operation_policy_for_pos(today=close)
            self.assertEqual((policy['can_renew'], policy['can_reenroll']), expected)
        item = source(end=end, next_date=close, deadline=close)
        item.wgs_domiciliation_contract_id = SimpleNamespace(
            state='active', wgs_get_operational_status=lambda **kw: {
                'state_key': 'renew', 'access_state': 'suspended', 'can_renew': True,
            },
        )
        self.assertTrue(item._wgs_subscription_operation_policy_for_pos(today=close)['can_renew'])

    def test_daily_quote_day_guards_all_positive_flows_and_old_signed_quotes(self):
        validate = method(OPS, '_wgs_validate_operation_source')
        owner = MagicMock()
        owner.env.__getitem__.return_value.browse.return_value.exists.return_value = False
        owner._wgs_get_subscription_business_today_for_pos.return_value = date(2026, 11, 26)
        for flow in ('new', 'renewal', 'reenroll', 'upsale'):
            for quoted_day in ('2026-11-25', '2026-11-27', False):
                with self.subTest(flow=flow, quoted_day=quoted_day), self.assertRaisesRegex(UserError, 'Cambio el dia'):
                    validate(owner, {'flow': flow, 'company_id': 9, 'pricing': {
                        'single_day_term': True, 'checkout_business_date': quoted_day,
                        'subscription_end_date': '2026-11-25',
                    }})
        self.assertFalse(validate(owner, {'company_id': 9, 'pricing': {
            'single_day_term': True, 'checkout_business_date': '2026-11-26',
            'subscription_end_date': '2026-12-01',
        }}))

    def test_monthly_and_domiciliation_quotes_are_not_expired_by_the_daily_guard(self):
        validate = method(OPS, '_wgs_validate_operation_source')
        owner = MagicMock()
        owner.env.__getitem__.return_value.browse.return_value.exists.return_value = False
        for pricing in ({'single_day_term': False}, {'single_day_term': True, 'domiciliation': {'contract_id': 1}}):
            self.assertFalse(validate(owner, {'company_id': 9, 'pricing': pricing}))
        owner._wgs_get_subscription_business_today_for_pos.assert_not_called()
