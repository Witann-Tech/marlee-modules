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
contacts = load('contacts')


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
        return parser.parse_file(data, filename, currency='MXN')

    def test_csv_preserves_identifiers_date_reference_and_descriptions(self):
        parsed = self.parse(self.csv())
        self.assertEqual(parsed.issues, [])
        self.assertEqual(parsed.read_count, 1)
        row = parsed.rows[0]
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

    def test_bank_columns_override_manual_amount_and_balance(self):
        columns = ['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE', 'DEPÓSITOS', 'RETIROS', 'SALDO']
        for manual in ('25', '', '-', 'bad', '999999'):
            with self.subTest(manual=manual):
                parsed = self.parse(self.csv(columns=columns, rows=[
                    ['0176055262', '12/10/2026', 'MXN', '1', manual, '$100.20', '-', '9999'],
                    ['0176055262', '12/10/2026', 'MXN', '2', manual, '-', '$40.10', '9999'],
                ]))
                self.assertEqual(parsed.issues, [])
                self.assertEqual([r.amount for r in parsed.rows], [Decimal('100.20'), Decimal('-40.10')])

    def test_invalid_bank_amount_cannot_fall_back_to_manual_amount(self):
        parsed = self.parse(self.csv(
            columns=['FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE', 'DEPÓSITOS', 'RETIROS'],
            rows=[['12/10/2026', 'MXN', '1', '100', 'bad', '-']],
        ))
        self.assertEqual(len(parsed.issues), 1)
        self.assertEqual(parsed.rows, [])

    def test_xlsx_original_bank_amounts_without_manual_column(self):
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active.append(['FECHA', 'MONEDA', 'MOVIMIENTO', 'DEPÓSITOS', 'RETIROS'])
        workbook.active.append([date(2026, 10, 12), 'MXP', '1', 23827.70, '-'])
        workbook.active.append([date(2026, 10, 12), 'MXP', '2', '-', 39997.80])
        output = io.BytesIO()
        workbook.save(output)
        parsed = self.parse(output.getvalue(), 'bank.xlsx')
        self.assertEqual(parsed.issues, [])
        self.assertEqual([r.amount for r in parsed.rows], [Decimal('23827.70'), Decimal('-39997.80')])

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

    def test_missing_movement_and_wrong_currency_report_rows(self):
        base = ['0176055262', '12/10/2026', 'MXN', '1', '100']
        for index, value in ((2, 'USD'), (3, '')):
            row = base.copy()
            row[index] = value
            parsed = self.parse(self.csv(columns=['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE'], rows=[row]))
            self.assertEqual(len(parsed.issues), 1)
            self.assertEqual(parsed.rows, [])

    def test_account_values_do_not_affect_import(self):
        parsed = self.parse(self.csv(columns=['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE'], rows=[
            ['0176055262', '12/10/2026', 'MXN', '1', '100'],
            ['9999999999', '12/10/2026', 'MXN', '2', '100'],
            ['', '12/10/2026', 'MXN', '3', '100'],
        ]))
        self.assertEqual(parsed.issues, [])
        self.assertEqual(len(parsed.rows), 3)

    def test_empty_files_unsupported_extension_and_overflow_columns(self):
        for data, filename in ((b'', 'a.csv'), (b'\n\n', 'a.csv'), (self.csv(rows=[]), 'a.csv'), (self.csv(), 'a.xls')):
            with self.subTest(filename=filename), self.assertRaises(parser.FileError):
                self.parse(data, filename)
        with self.assertRaises(parser.FileError):
            self.parse(self.csv(columns=['A'] * 101))

    def test_account_column_is_optional(self):
        parsed = self.parse(self.csv(
            columns=['FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE'],
            rows=[['12/10/2026', 'MXN', '1', '100']],
        ))
        self.assertEqual(parsed.issues, [])
        self.assertEqual(parsed.rows[0].movement, '1')

    def test_xlsx_account_column_is_ignored_for_280_rows(self):
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE'])
        accounts = [None, 176055262, '072180017605526201', '=1+1', '#VALUE!']
        for index in range(280):
            sheet.append([accounts[index % len(accounts)], date(2026, 10, 12), 'MXN', str(31984 + index), 100])
        output = io.BytesIO()
        workbook.save(output)
        parsed = self.parse(output.getvalue(), 'bank.xlsx')
        self.assertEqual(parsed.issues, [])
        self.assertEqual(len(parsed.rows), 280)

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
        self.assertEqual(parsed.rows[0].amount, Decimal('18872.11'))

    def test_xlsx_rejects_long_numeric_movement_and_used_formulas(self):
        from openpyxl import Workbook
        for account, movement, amount in (('0176055262', 1234567890123456, 100), ('0176055262', 1, '=1+1')):
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


class ContactTests(unittest.TestCase):
    def test_rfc_normalization_and_invalid_fiscal_identifiers(self):
        for raw in ('GAMA900101AB1', 'mx gama900101ab1', 'MX-GAMA-900101-AB1'):
            self.assertEqual(contacts.normalize_rfc(raw), 'GAMA900101AB1')
        self.assertEqual(contacts.normalize_rfc('ABC010101AB1'), 'ABC010101AB1')
        for raw in (False, '', 'XAXX010101000', 'MX XEXX010101000', 'GAMA900101HASRZS05',
                    'GAMA900231AB1', 'GAMA901301AB1', 'ABC', 'ABC010101AB123'):
            with self.subTest(raw=raw):
                self.assertEqual(contacts.normalize_rfc(raw), '')

    def test_name_normalization_preserves_enye_and_removes_bank_separators(self):
        self.assertEqual(contacts.normalize_name('  Mateo Alejandro,Solís/Fuentes '), 'MATEO ALEJANDRO SOLIS FUENTES')
        self.assertNotEqual(contacts.normalize_name('Luis Peña'), contacts.normalize_name('Luis Pena'))

    def test_extract_explicit_client_and_beneficiary_names(self):
        client = contacts.extract_contact('SPEI RECIBIDO, DEL CLIENTE MATEO ALEJANDRO,SOLIS/FUENTES, DE LA CLABE 123 CON RFC GAMA900101AB1, CONCEPTO: pago', 100)
        self.assertEqual(client, contacts.Contact('MATEO ALEJANDRO,SOLIS/FUENTES', 'GAMA900101AB1'))
        beneficiary = contacts.extract_contact('BEM SPEI, BENEF:Mateo Alejandro Solis Fuente (DATO NO VERIFICADO, POR ESTA INSTITUCION), pago, RFC: GAMA900101AB1, IVA: 0', -100)
        self.assertEqual(beneficiary, contacts.Contact('Mateo Alejandro Solis Fuente', 'GAMA900101AB1'))

    def test_extract_tef_direct_debit_and_rfc_without_name(self):
        tef = contacts.extract_contact('BEM TEF.BCO:012  Juan Manuel Garcia Perez, CVE.RASTREO:123 RFC: GAMA900101AB1 IVA:0', -100)
        self.assertEqual(tef.name, 'Juan Manuel Garcia Perez')
        debit = contacts.extract_contact('CARGO COBRANZA DOMICILIADA, REF:123, COBRADOR SA DE CV, RFC: ABC010101AB1 IVA:0', -100)
        self.assertEqual(debit, contacts.Contact('COBRADOR SA DE CV', 'ABC010101AB1'))
        self.assertEqual(contacts.extract_contact('A LA CUENTA 123, prestamo AL R.F.C. GAMA900101AB1', -100), contacts.Contact('', 'GAMA900101AB1'))

    def test_malformed_missing_concepts_and_direction_conflicts_are_optional(self):
        for detail, amount in (('', 100), ('padel Juan Garcia', 100), ('Mensualidad Israel y Fabiola', 100),
                               ('BENEF:Juan Garcia sin delimitador', -100), ('X' * 8193, 100),
                               ('DEL CLIENTE JUAN GARCIA, DE LA CLABE 123', -100),
                               ('BENEF:JUAN GARCIA (DATO NO VERIFICADO)', 100),
                               ('AL RFC GAMA900101AB1', 0)):
            with self.subTest(detail=detail[:70], amount=amount):
                self.assertEqual(contacts.extract_contact(detail, amount), contacts.Contact())

    def test_conflicting_explicit_contacts_are_ignored(self):
        for detail in ('AL RFC GAMA900101AB1 CON RFC ABC010101AB1',
                       'DEL CLIENTE JUAN GARCIA, DE LA CLABE 123, DEL CLIENTE PEDRO LOPEZ, DE LA CLABE 456'):
            self.assertEqual(contacts.extract_contact(detail, 100), contacts.Contact())

    def test_curp_and_generic_rfc_do_not_prevent_name_extraction(self):
        for rfc in ('GAMA900101HASRZS05', 'XAXX010101000'):
            contact = contacts.extract_contact(f'DEL CLIENTE JUAN MANUEL GARCIA, DE LA CLABE 123 CON RFC {rfc}, CONCEPTO: pago', 100)
            self.assertEqual(contact, contacts.Contact('JUAN MANUEL GARCIA', ''))

    def test_exact_unique_rfc_with_missing_or_truncated_name(self):
        matcher = contacts.Matcher([contacts.Partner(7, 'Mateo Alejandro Solis Fuentes', 'MXGAMA900101AB1')])
        for name in ('', 'Mateo Alejandro Solis Fuente'):
            self.assertEqual(matcher.match(contacts.Contact(name, 'GAMA900101AB1')), 7)

    def test_duplicate_rfc_does_not_choose_even_an_exact_name(self):
        matcher = contacts.Matcher([contacts.Partner(7, 'Juan Manuel Garcia', 'GAMA900101AB1'),
                                    contacts.Partner(8, 'Otra Persona', 'GAMA900101AB1')])
        self.assertIsNone(matcher.match(contacts.Contact('Juan Manuel Garcia', 'GAMA900101AB1')))

    def test_rfc_name_contradiction_and_name_rfc_contradiction_are_unmatched(self):
        matcher = contacts.Matcher([contacts.Partner(7, 'Mateo Alejandro Solis Fuentes', 'GAMA900101AB1')])
        self.assertIsNone(matcher.match(contacts.Contact('Ernesto Beltran Hurtado', 'GAMA900101AB1')))
        self.assertIsNone(matcher.match(contacts.Contact('Mateo Alejandro Solis Fuentes', 'ABC010101AB1')))
        matcher = contacts.Matcher([contacts.Partner(7, 'Juan Carlos Lopez', 'GAMA900101AB1')])
        self.assertIsNone(matcher.match(contacts.Contact('Juan Manuel Garcia', 'GAMA900101AB1')))

    def test_rfc_allows_a_company_short_name_with_the_same_distinctive_name(self):
        matcher = contacts.Matcher([contacts.Partner(7, 'STRIPE', 'ABC010101AB1')])
        self.assertEqual(matcher.match(contacts.Contact('STRIPE PAYMENTS MEXICO S DE RL DE CV', 'ABC010101AB1')), 7)

    def test_fuzzy_name_matching_does_not_treat_enye_as_an_accent(self):
        matcher = contacts.Matcher([contacts.Partner(7, 'Luis Alejandro Rodriguez Cañizares')])
        self.assertIsNone(matcher.match(contacts.Contact('Luis Alejandro Rodriguez Canizares')))

    def test_exact_normalized_and_reordered_names_match(self):
        matcher = contacts.Matcher([contacts.Partner(7, 'García Pérez Juan Manuel')])
        self.assertEqual(matcher.match(contacts.Contact('JUAN MANUEL,GARCIA/PEREZ')), 7)

    def test_corporate_punctuation_matches_without_mutating_name(self):
        matcher = contacts.Matcher([contacts.Partner(7, 'SERVICIOS MODELO SAPI DE CV')])
        self.assertEqual(matcher.match(contacts.Contact('SERVICIOS MODELO, S.A.P.I. DE C.V.')), 7)

    def test_unique_small_truncation_matches_with_enough_full_tokens(self):
        matcher = contacts.Matcher([contacts.Partner(7, 'Mateo Alejandro Solis Fuentes')])
        self.assertEqual(matcher.match(contacts.Contact('Mateo Alejandro Solis Fuente')), 7)

    def test_duplicate_names_and_close_runner_up_do_not_match(self):
        for second in ('Mateo Alejandro Solis Fuentes', 'Mateo Alejandro Solis Fuente'):
            matcher = contacts.Matcher([contacts.Partner(7, 'Mateo Alejandro Solis Fuentes'), contacts.Partner(8, second)])
            self.assertIsNone(matcher.match(contacts.Contact('Mateo Alejandro Solis Fuentes')))

    def test_short_generic_partial_or_multiple_spelling_differences_do_not_match(self):
        matcher = contacts.Matcher([contacts.Partner(7, 'Juan Manuel Garcia Perez'),
                                    contacts.Partner(8, 'PUBLICO EN GENERAL'), contacts.Partner(9, 'OXXO'),
                                    contacts.Partner(10, 'Jose Ramos'), contacts.Partner(11, 'Luis Peña')])
        for name in ('Juan Garcia', 'Juan', 'Juan Manul Garcia Perz', 'PUBLICO EN GENERAL', 'OXXO', 'Jose Ramon', 'Luis Pena'):
            with self.subTest(name=name):
                self.assertIsNone(matcher.match(contacts.Contact(name)))

    def test_empty_catalogue_and_invalid_rfc_only_are_unmatched(self):
        self.assertIsNone(contacts.Matcher([]).match(contacts.Contact('Juan Garcia', 'GAMA900101AB1')))
        matcher = contacts.Matcher([contacts.Partner(7, 'Juan Garcia', 'XAXX010101000')])
        self.assertIsNone(matcher.match(contacts.Contact('', 'XAXX010101000')))


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.row = parser.Row(2, '31984', date(2026, 10, 12), Decimal('100.00'), 'REF', 'Pago')

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
