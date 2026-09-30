from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase


class TestSubscriptionCalendar(TransactionCase):
    def test_validity_fields_store_calendar_dates_without_purchase_time(self):
        for model, field_names in (
            ('sale.order', ('wgs_effective_start_date', 'start_date', 'end_date', 'next_invoice_date')),
            ('wgs.subscription.domiciliation.contract', ('access_start_date', 'term_start_date', 'term_end_date')),
        ):
            for field_name in field_names:
                with self.subTest(model=model, field=field_name):
                    self.assertEqual(self.env[model]._fields[field_name].type, 'date')

    def test_calendar_conversions_agree_at_mexico_midnight(self):
        Order = self.env['sale.order']
        PosOrder = self.env['pos.order']
        for value, expected in (
            (datetime(2026, 9, 15, 5, 59, 59), date(2026, 9, 14)),
            (datetime(2026, 9, 15, 6), date(2026, 9, 15)),
            (datetime(2026, 9, 16, 0), date(2026, 9, 15)),
            (datetime(2026, 10, 15, 5, 59, 59), date(2026, 10, 14)),
            (datetime(2026, 10, 15, 6), date(2026, 10, 15)),
            (datetime(2026, 9, 15, 2, 23, tzinfo=timezone.utc), date(2026, 9, 14)),
        ):
            with self.subTest(value=value):
                self.assertEqual(Order._wgs_get_subscription_business_today(now=value), expected)
                self.assertEqual(Order._wgs_get_subscription_business_date_from_datetime(value), expected)
                self.assertEqual(Order._to_date(value), expected)
                self.assertEqual(PosOrder._wgs_to_date(value), expected)

    def test_calendar_dates_are_not_shifted_as_utc_timestamps(self):
        for value in (date(2026, 9, 15), '2026-09-15'):
            with self.subTest(value=value):
                self.assertEqual(self.env['sale.order']._to_date(value), date(2026, 9, 15))
                self.assertEqual(self.env['pos.order']._wgs_to_date(value), date(2026, 9, 15))
        for value in (False, None):
            with self.subTest(value=value):
                self.assertFalse(self.env['sale.order']._to_date(value))
                self.assertFalse(self.env['pos.order']._wgs_to_date(value))

    def test_pos_datetime_fallback_matches_subscription_access_calendar(self):
        order = self.env['sale.order'].new({'date_order': datetime(2026, 9, 15, 2, 23)})
        self.assertEqual(order._get_first_available_date(('date_order',)), date(2026, 9, 14))
        self.assertEqual(order._wgs_get_first_access_date_value(('date_order',)), date(2026, 9, 14))

    def test_access_includes_both_whole_calendar_days(self):
        Order = self.env['sale.order']
        cases = (
            ('2026-09-15', '2026-10-14', '2026-10-15'),
            # Legacy records can use the inclusive end as next_invoice_date.
            ('2026-09-15', '2026-10-14', '2026-10-14'),
            ('2026-10-14', '2026-10-14', False),
        )
        with patch.object(type(Order), '_wgs_is_confirmed_access_subscription_order', return_value=True):
            for start, end, next_invoice in cases:
                order = Order.new({
                    'company_id': self.env.company.id,
                    'subscription_state': '3_progress',
                    'wgs_effective_start_date': start,
                    'start_date': start,
                    'end_date': end,
                    'next_invoice_date': next_invoice,
                })
                local_start = datetime.combine(date.fromisoformat(start), datetime.min.time())
                local_end = datetime.combine(date.fromisoformat(end), datetime.max.time())
                business_tz = order._wgs_get_subscription_business_timezone()
                for local_now, expected in (
                    (local_start - timedelta(microseconds=1), False),
                    (local_start, 'enabled'),
                    (local_end.replace(microsecond=0), 'enabled'),
                    (local_end, 'enabled'),
                    (local_end + timedelta(microseconds=1), False),
                ):
                    utc_now = business_tz.localize(local_now).astimezone(timezone.utc).replace(tzinfo=None)
                    with self.subTest(start=start, end=end, next_invoice=next_invoice, local_now=local_now):
                        with patch.object(fields.Datetime, 'now', return_value=utc_now):
                            self.assertEqual(order._wgs_classify_subscription_access_state(), expected)
