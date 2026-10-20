import importlib.util
from datetime import date, datetime
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[2] / 'witann_payroll_pos_commission' / 'calculation.py'
spec = importlib.util.spec_from_file_location('pos_commission_calculation', PATH)
calculation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calculation)


class TestCommissionCalculation(unittest.TestCase):
    def test_monthly_one_percent_split(self):
        self.assertEqual(calculation.commission_amount(100000, 1), 500)
        self.assertEqual(calculation.commission_amount(100000, 1, True), 500)

    def test_configurable_zero_and_negative_base(self):
        self.assertEqual(calculation.commission_amount(100000, 2), 1000)
        self.assertEqual(calculation.commission_amount(100000, 0), 0)
        self.assertEqual(calculation.commission_amount(-100000, 1), 0)

    def test_odd_cent_is_not_paid_twice(self):
        self.assertEqual(calculation.commission_amount(101, 1), 0.51)
        self.assertEqual(calculation.commission_amount(101, 1, True), 0.50)

    def test_invalid_rate(self):
        for rate in (-1, 101, float('nan'), float('inf')):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                calculation.commission_amount(100, rate)

    def test_previous_year(self):
        _, month, start, stop = calculation.commission_period(date(2027, 1, 1), date(2027, 1, 15), 'America/Mexico_City')
        self.assertEqual(month, date(2026, 12, 1))
        self.assertEqual(start, datetime(2026, 12, 1, 6))
        self.assertEqual(stop, datetime(2027, 1, 1, 6))

    def test_both_fortnights_same_reference_month(self):
        first = calculation.commission_period(date(2026, 10, 1), date(2026, 10, 15), 'America/Mexico_City')
        second = calculation.commission_period(date(2026, 10, 16), date(2026, 10, 31), 'America/Mexico_City')
        self.assertEqual(first[1:], second[1:])

    def test_february_and_leap_year(self):
        for year, end in ((2026, 28), (2024, 29)):
            period, month, _, _ = calculation.commission_period(date(year, 2, 16), date(year, 2, end), 'UTC')
            self.assertEqual(month, date(year, 1, 1))
            self.assertEqual(period, date(year, 2, 16))

    def test_invalid_periods(self):
        for first, last in ((1, 31), (2, 15), (16, 30), (15, 31)):
            with self.subTest(first=first, last=last), self.assertRaises(ValueError):
                calculation.commission_period(date(2026, 10, first), date(2026, 10, last), 'UTC')


if __name__ == '__main__':
    unittest.main()
