"""File parsing/classification tests; no Odoo accounting runtime is simulated.

Run with Python + openpyxl. The addon also includes separate Odoo ORM tests.
"""
import csv
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

ROOT = Path(__file__).resolve().parents[2] / 'witann_bank_import_deduplicate'


def load(name):
    spec = importlib.util.spec_from_file_location('witann_bank_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


parser = load('parser')
dedup = load('deduplicate')


def compare(left, right):
    def rounded(value):
        return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    return (rounded(left) > rounded(right)) - (rounded(left) < rounded(right))


class BankFileTests(unittest.TestCase):
    def csv(self, rows=None, *, columns=None, delimiter=',', encoding='utf-8-sig'):
        columns = columns or ['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE', 'REFERENCIA', 'DESCRIPCIÓN', 'DESCRIPCIÓN DETALLADA', 'SALDO']
        rows = rows if rows is not None else [["'017 605 5262", '03/04/2026', 'MXP', '0031984', '$18,872.11', 'REF-01', 'Depósito', 'Cliente A', '999999.00']]
        output = io.StringIO(newline='')
        writer = csv.writer(output, delimiter=delimiter)
        writer.writerow(columns)
        writer.writerows(rows)
        return output.getvalue().encode(encoding)

    def parse(self, data, filename='bank.csv'):
        return parser.parse_file(data, filename, account='0176055262', currency='MXN')

    def test_csv_preserves_identifiers_date_reference_and_descriptions(self):
        parsed = self.parse(self.csv())
        self.assertEqual(parsed.issues, [])
        self.assertEqual(parsed.read_count, 1)
        row = parsed.rows[0]
        self.assertEqual(row.account, '0176055262')
        self.assertEqual(row.movement, '0031984')
        self.assertEqual(row.date, date(2026, 4, 3))
        self.assertEqual(row.amount, Decimal('18872.11'))
        self.assertEqual(row.reference, 'REF-01')
        self.assertEqual(row.label, 'Depósito / Cliente A')

    def test_semicolon_cp1252_and_accentless_headers(self):
        parsed = self.parse(self.csv(delimiter=';', encoding='cp1252'))
        self.assertEqual(parsed.issues, [])
        parsed = self.parse(self.csv(columns=[' cuenta ', ' fecha ', 'moneda', 'movimiento', 'importe'], rows=[['0176055262', '12/10/2026', 'mxn', '31984', '-100.50']]))
        self.assertEqual(parsed.rows[0].amount, Decimal('-100.50'))

    def test_deposits_minus_withdrawals_and_blank_rows(self):
        columns = ['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'DEPÓSITOS', 'RETIROS']
        rows = [
            ['0176055262', '12/10/2026', 'MXN', '1', '$100.20', '-'],
            ['', '', '', '', '', ''],
            ['0176055262', '12/10/2026', 'MXN', '2', '', '40.10'],
            ['0176055262', '12/10/2026', 'MXN', '3', '-', ''],
        ]
        parsed = self.parse(self.csv(columns=columns, rows=rows))
        self.assertEqual(parsed.issues, [])
        self.assertEqual(parsed.read_count, 3)
        self.assertEqual([r.amount for r in parsed.rows], [Decimal('100.20'), Decimal('-40.10'), Decimal(0)])
        self.assertEqual([r.number for r in parsed.rows], [2, 4, 5])

    def test_explicit_amount_wins_over_other_amount_columns_and_balance(self):
        columns = ['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE', 'DEPÓSITOS', 'RETIROS', 'SALDO']
        parsed = self.parse(self.csv(columns=columns, rows=[['0176055262', '12/10/2026', 'MXN', '1', '25', 'bad', 'bad', '9999']]))
        self.assertEqual(parsed.rows[0].amount, Decimal(25))

    def test_complete_bank_format_uses_fecha_instead_of_operation_date(self):
        columns = ['CUENTA', 'FECHA DE OPERACIÓN', 'FECHA', 'REFERENCIA', 'DESCRIPCIÓN', 'COD. TRANSAC', 'SUCURSAL', 'DEPÓSITOS', 'RETIROS', 'SALDO', 'MONEDA', 'MOVIMIENTO', 'DESCRIPCIÓN DETALLADA', 'CHEQUE']
        parsed = self.parse(self.csv(columns=columns, rows=[[
            '0176055262', '01/03/2026', '03/04/2026', 'REF', 'Pago', 'X', 'Y',
            '100', '5', '9999', 'MXP', '31984', 'Detalle', 'CHK',
        ]]))
        self.assertEqual(parsed.issues, [])
        self.assertEqual(parsed.rows[0].date, date(2026, 4, 3))
        self.assertEqual(parsed.rows[0].amount, Decimal(95))

    def test_invalid_explicit_amount_never_becomes_zero(self):
        for value in ('', '-', 'abc', 'NaN', 'Infinity', '1,23', '18.872,11', '$', '1e3'):
            with self.subTest(value=value):
                parsed = self.parse(self.csv(columns=['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE'], rows=[['0176055262', '12/10/2026', 'MXN', '1', value]]))
                self.assertEqual(len(parsed.issues), 1)
                self.assertEqual(parsed.rows, [])
                self.assertEqual(parsed.issues[0].number, 2)

    def test_invalid_numeric_amounts(self):
        for value in (True, float('nan'), float('inf'), Decimal('NaN')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parser.parse_amount(value)

    def test_numeric_and_parenthesized_amounts(self):
        for value, expected in ((18872.11, '18872.11'), (0, '0'), ('($18,872.11)', '-18872.11'), ('$-100.20', '-100.20')):
            self.assertEqual(parser.parse_amount(value), Decimal(expected))

    def test_negative_deposit_or_withdrawal_is_invalid(self):
        parsed = self.parse(self.csv(columns=['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'DEPÓSITOS', 'RETIROS'], rows=[['0176055262', '12/10/2026', 'MXN', '1', '-100', '0']]))
        self.assertEqual(len(parsed.issues), 1)

    def test_date_is_strict_day_first_and_calendar_valid(self):
        for value in ('04/13/2026', '31/02/2026', '2026-10-12', '1/2/2026', 46000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parser.parse_date(value)
        self.assertEqual(parser.parse_date('12/10/2026'), date(2026, 10, 12))
        self.assertEqual(parser.parse_date(datetime(2026, 10, 12, 13)), date(2026, 10, 12))

    def test_required_headers_and_duplicate_headers(self):
        for columns in (
            ['FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE'],
            ['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO'],
            ['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'DEPÓSITOS'],
            ['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE', 'importe'],
        ):
            with self.subTest(columns=columns), self.assertRaises(parser.FileError):
                self.parse(self.csv(columns=columns, rows=[]))

    def test_missing_movement_account_and_wrong_currency_report_rows(self):
        base = ['0176055262', '12/10/2026', 'MXN', '1', '100']
        for index, value in ((0, ''), (0, '176055262'), (2, 'USD'), (3, '')):
            row = base.copy()
            row[index] = value
            parsed = self.parse(self.csv(columns=['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE'], rows=[row]))
            self.assertEqual(len(parsed.issues), 1)
            self.assertEqual(parsed.rows, [])

    def test_multiple_accounts_rejected_even_if_one_account_matches(self):
        parsed = self.parse(self.csv(columns=['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE'], rows=[
            ['0176055262', '12/10/2026', 'MXN', '1', '100'],
            ['9999999999', '12/10/2026', 'MXN', '2', '100'],
        ]))
        self.assertTrue(any('varias cuentas' in i.message for i in parsed.issues))

    def test_empty_files_unsupported_extension_and_overflow_columns(self):
        for data, filename in ((b'', 'a.csv'), (b'\n\n', 'a.csv'), (self.csv(rows=[]), 'a.csv'), (self.csv(), 'a.xls')):
            with self.subTest(filename=filename), self.assertRaises(parser.FileError):
                self.parse(data, filename)
        with self.assertRaises(parser.FileError):
            self.parse(self.csv(columns=['A'] * 101))

    def test_missing_bank_configuration_is_empty(self):
        self.assertEqual(parser.normalize_account(False), '')
        self.assertEqual(parser.normalize_account(None), '')
        self.assertEqual(parser.normalize_account(" '000 123 " ), '000123')

    def test_xlsx_text_accounts_numeric_amounts_and_real_dates(self):
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE'])
        sheet.append(['0176055262', datetime(2026, 4, 3), 'MXP', '0031984', 18872.11])
        sheet.append([176055262, '04/04/2026', 'MXN', 31985, -5.10])
        sheet['A3'].number_format = '0000000000'
        sheet['D3'].number_format = '0000000'
        output = io.BytesIO()
        workbook.save(output)
        parsed = self.parse(output.getvalue(), 'bank.xlsx')
        self.assertEqual(parsed.issues, [])
        self.assertEqual([r.movement for r in parsed.rows], ['0031984', '0031985'])
        self.assertEqual(parsed.rows[1].account, '0176055262')
        self.assertEqual(parsed.rows[0].amount, Decimal('18872.11'))

    def test_xlsx_rejects_ambiguous_account_long_numeric_id_and_formulas(self):
        from openpyxl import Workbook
        for account, movement, amount in ((176055262, 1, 100), ('0176055262', 1234567890123456, 100), ('0176055262', 1, '=1+1')):
            with self.subTest(account=account, movement=movement, amount=amount):
                workbook = Workbook()
                workbook.active.append(['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE'])
                workbook.active.append([account, date(2026, 10, 12), 'MXN', movement, amount])
                output = io.BytesIO()
                workbook.save(output)
                parsed = self.parse(output.getvalue(), 'bank.xlsx')
                self.assertEqual(len(parsed.issues), 1)

    def test_xlsx_rejects_extra_nonempty_sheets(self):
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active.append(['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE'])
        workbook.active.append(['0176055262', date(2026, 10, 12), 'MXN', '1', 1])
        workbook.create_sheet().append(['Unexpected other account'])
        output = io.BytesIO()
        workbook.save(output)
        with self.assertRaises(parser.FileError):
            self.parse(output.getvalue(), 'bank.xlsx')

    def test_invalid_xlsx(self):
        with self.assertRaises(parser.FileError):
            self.parse(b'not a zip', 'bank.xlsx')

    def test_corrupt_xlsx_xml_has_a_clear_file_error(self):
        import zipfile
        from openpyxl import Workbook
        valid = io.BytesIO()
        Workbook().save(valid)
        broken = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(valid.getvalue())) as source, zipfile.ZipFile(broken, 'w') as target:
            for name in source.namelist():
                target.writestr(name, b'<broken' if name == 'xl/workbook.xml' else source.read(name))
        with self.assertRaises(parser.FileError):
            self.parse(broken.getvalue(), 'bank.xlsx')

    def test_invalid_csv_encoding_has_a_clear_file_error(self):
        with self.assertRaises(parser.FileError):
            self.parse(b'\x81', 'bank.csv')


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.row = parser.Row(2, '31984', '0176055262', date(2026, 10, 12), Decimal('100.00'), 'REF', 'Pago')

    def existing(self, **kwargs):
        return dedup.Existing(**dict(id=87, date=self.row.date, amount=100, **kwargs))

    def classify(self, rows=None, candidates=None):
        return dedup.classify(rows or [self.row], {self.row.movement: candidates} if candidates else {}, compare)

    def test_new_then_existing(self):
        self.assertEqual(self.classify()[0].status, 'new')
        result = self.classify(candidates=[self.existing()])[0]
        self.assertEqual(result.status, 'existing')
        self.assertEqual(result.existing_id, 87)

    def test_amounts_compare_at_currency_precision(self):
        result = self.classify([replace(self.row, amount=Decimal('100.004'))], [self.existing()])
        self.assertEqual(result[0].status, 'existing')
        result = self.classify([replace(self.row, amount=Decimal('100.01'))], [self.existing()])
        self.assertEqual(result[0].status, 'conflict')

    def test_changed_date_or_existing_identifier_is_conflict(self):
        for candidate in (replace(self.existing(), date=date(2026, 10, 11)), replace(self.existing(), movement='OTHER')):
            self.assertEqual(self.classify(candidates=[candidate])[0].status, 'conflict')

    def test_compatible_repetitions(self):
        rows = [self.row, replace(self.row, number=4, label='Different description')]
        self.assertEqual([r.status for r in self.classify(rows)], ['new', 'duplicate'])
        self.assertEqual([r.status for r in self.classify(rows, [self.existing()])], ['existing', 'duplicate'])

    def test_incompatible_repetitions_conflict_for_the_whole_group(self):
        for changed in (replace(self.row, number=3, amount=Decimal(101)), replace(self.row, number=3, date=date(2026, 10, 11))):
            result = self.classify([self.row, changed, replace(self.row, number=4)])
            self.assertEqual([r.status for r in result], ['conflict'] * 3)

    def test_ambiguous_legacy_mapping_is_conflict(self):
        result = self.classify(candidates=[self.existing(), replace(self.existing(), id=88)])
        self.assertEqual(result[0].status, 'conflict')

    def test_single_legacy_record_claiming_multiple_identifiers_is_conflict(self):
        result = self.classify(candidates=[self.existing(legacy=True, ambiguous=True)])
        self.assertEqual(result[0].status, 'conflict')

    def test_legacy_match_reports_origin(self):
        result = self.classify(candidates=[self.existing(legacy=True)])
        self.assertIn('ID externo', result[0].message)
        self.assertEqual(result[0].status, 'existing')

    def test_no_heuristic_match_by_amount_and_date(self):
        result = dedup.classify([self.row], {'OTHER': [self.existing()]}, compare)
        self.assertEqual(result[0].status, 'new')

    def test_280_rows_and_overlapping_period(self):
        first = [replace(self.row, number=i + 2, movement=str(i)) for i in range(280)]
        self.assertEqual(sum(r.status == 'new' for r in dedup.classify(first, {}, compare)), 280)
        existing = {row.movement: [replace(self.existing(), id=i + 1)] for i, row in enumerate(first)}
        self.assertEqual(sum(r.status == 'new' for r in dedup.classify(first, existing, compare)), 0)
        overlap = [replace(self.row, number=i + 2, movement=str(i + 140)) for i in range(280)]
        result = dedup.classify(overlap, existing, compare)
        self.assertEqual(sum(r.status == 'new' for r in result), 140)
        self.assertEqual(sum(r.status == 'existing' for r in result), 140)


if __name__ == '__main__':
    unittest.main()
