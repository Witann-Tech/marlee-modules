import base64
import csv
import io
import logging
import time
from datetime import date
from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestBankImport(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls.company_data['default_journal_bank']
        cls.journal.bank_account_id = cls.env['res.partner.bank'].create({
            'acc_number': '0176055262',
            'partner_id': cls.journal.company_id.partner_id.id,
        })
        cls.Line = cls.env['account.bank.statement.line']
        cls.Wizard = cls.env['witann.bank.import']

    def _csv(self, rows, journal=None):
        journal = journal or self.journal
        currency = journal.currency_id or journal.company_id.currency_id
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE', 'REFERENCIA', 'DESCRIPCIÓN', 'DESCRIPCIÓN DETALLADA', 'SALDO'])
        for row in rows:
            movement, amount, *dates = row
            writer.writerow([
                journal.bank_account_id.acc_number, dates[0] if dates else '12/10/2026',
                currency.name, movement, amount, 'REF-' + str(movement), 'Pago', 'Detalle', '999999',
            ])
        return base64.b64encode(output.getvalue().encode('utf-8-sig'))

    def _wizard(self, rows, journal=None, user=None):
        journal = journal or self.journal
        model = self.Wizard.with_company(journal.company_id)
        if user:
            model = model.with_user(user).with_context(allowed_company_ids=[journal.company_id.id])
        return model.create({
            'journal_id': journal.id,
            'filename': 'bank.csv',
            'file_data': self._csv(rows, journal),
        })

    def _line(self, movement='31984', amount=100, journal=None, **extra):
        journal = journal or self.journal
        return self.Line.with_company(journal.company_id).create({
            'journal_id': journal.id,
            'date': '2026-10-12',
            'amount': amount,
            'payment_ref': 'Original',
            'witann_bank_movement': movement,
            **extra,
        })

    def _xmlid(self, name, record, model=None, module='__import__'):
        return self.env['ir.model.data'].sudo().create({
            'module': module,
            'name': name,
            'model': model or record._name,
            'res_id': record.id,
        })

    def _legacy_movement(self, suffix=0):
        # Keep global __import__ names independent of a staging copy's real IDs.
        return str(10**30 + self.journal.id * 100 + suffix)

    def _snapshot(self, lines):
        """Compare actual stored rows, including write dates and reconciliation IDs."""
        self.env.flush_all()
        moves = lines.move_id
        items = moves.line_ids
        partials = items.matched_debit_ids | items.matched_credit_ids
        fulls = items.full_reconcile_id
        result = {}
        for model, records in (
            ('account_bank_statement_line', lines),
            ('account_move', moves),
            ('account_move_line', items),
            ('account_partial_reconcile', partials),
            ('account_full_reconcile', fulls),
        ):
            # All identifiers above are fixed literals, not file/user values.
            self.env.cr.execute(f'SELECT * FROM {model} WHERE id = ANY(%s) ORDER BY id', [records.ids])
            result[model] = self.env.cr.fetchall()
        return result

    def _forbid_accounting_mutation(self):
        # Used when every file row is already present. Any write/unlink/create,
        # including a harmless-looking identifier backfill, must fail this test.
        from contextlib import ExitStack
        stack = ExitStack()
        for model in ('account.bank.statement.line', 'account.move', 'account.move.line',
                      'account.partial.reconcile', 'account.full.reconcile'):
            for method in ('create', 'write', 'unlink'):
                stack.enter_context(patch.object(type(self.env[model]), method, side_effect=AssertionError(f'Unexpected {model}.{method}')))
        return stack

    def test_first_import_native_moves_and_identical_reimport_do_not_write(self):
        wizard = self._wizard([('31984', 100), ('31985', -40)])
        wizard.action_import()
        self.assertEqual(wizard.created_count, 2)
        self.assertEqual(wizard.read_count, 2)
        self.assertEqual(wizard.skipped_count, 0)
        lines = wizard.created_line_ids
        self.assertEqual(set(lines.move_id.mapped('state')), {'posted'})
        self.assertTrue(all(len(line.move_id.line_ids) == 2 for line in lines))
        self.assertEqual(lines[0].ref, 'REF-31984')
        self.assertEqual(lines[0].payment_ref, 'Pago / Detalle')
        before = self._snapshot(lines)
        second = self._wizard([('31984', 100), ('31985', -40)])
        with self._forbid_accounting_mutation():
            second.action_analyze()
            second.action_import()
        self.assertEqual(second.created_count, 0)
        self.assertEqual(second.skipped_count, 2)
        self.assertEqual(self._snapshot(lines), before)

    def test_overlap_only_creates_difference_and_keeps_existing_intact(self):
        first = self._wizard([('1', 100), ('2', 200)])
        first.action_import()
        before = self._snapshot(first.created_line_ids)
        second = self._wizard([('2', 200), ('3', 300)])
        second.action_import()
        self.assertEqual(second.created_count, 1)
        self.assertEqual(second.skipped_count, 1)
        self.assertEqual(second.created_line_ids.witann_bank_movement, '3')
        self.assertEqual(self._snapshot(first.created_line_ids), before)

    def test_analyze_never_creates_accounting_records(self):
        wizard = self._wizard([('31984', 100)])
        counts = {model: self.env[model].search_count([]) for model in (
            'account.bank.statement.line', 'account.move', 'account.move.line',
            'account.partial.reconcile', 'account.full.reconcile',
        )}
        with self._forbid_accounting_mutation():
            wizard.action_analyze()
        self.assertEqual(wizard.new_count, 1)
        for model, count in counts.items():
            self.assertEqual(self.env[model].search_count([]), count)

    def test_import_rechecks_after_analysis(self):
        wizard = self._wizard([('31984', 100)])
        wizard.action_analyze()
        self.assertEqual(wizard.new_count, 1)
        existing = self._line()
        before = self._snapshot(existing)
        wizard.action_import()
        self.assertEqual(wizard.created_count, 0)
        self.assertEqual(wizard.existing_count, 1)
        self.assertEqual(self._snapshot(existing), before)

    def test_existing_conflicts_block_whole_file(self):
        existing = self._line()
        before = self._snapshot(existing)
        for row in (('31984', 101), ('31984', 100, '11/10/2026')):
            wizard = self._wizard([('new', 50), row])
            wizard.action_analyze()
            self.assertEqual(wizard.conflict_count, 1)
            wizard.action_import()
            self.assertEqual(wizard.created_count, 0)
            self.assertFalse(self.Line.search([('witann_bank_movement', '=', 'new')]))
            self.assertEqual(self._snapshot(existing), before)

    def test_duplicate_rows_report_and_process_once(self):
        wizard = self._wizard([('31984', 100), ('31984', '100.004')])
        wizard.action_import()
        self.assertEqual(wizard.created_count, 1)
        self.assertEqual(wizard.duplicate_count, 1)
        self.assertEqual(wizard.skipped_count, 1)
        self.assertEqual(wizard.read_count, 2)

    def test_incompatible_repeated_identifier_blocks_all_rows(self):
        for rows in (
            [('31984', 100), ('31984', 101)],
            [('31984', 100), ('31984', 100, '11/10/2026')],
        ):
            wizard = self._wizard(rows)
            wizard.action_import()
            self.assertEqual(wizard.conflict_count, 2)
            self.assertEqual(wizard.created_count, 0)

    def test_invalid_row_blocks_other_new_rows(self):
        wizard = self._wizard([('new', 50), ('bad', '-')])
        wizard.action_import()
        self.assertEqual(wizard.invalid_count, 1)
        self.assertEqual(wizard.result_ids.filtered(lambda row: row.status == 'invalid').row_number, 3)
        self.assertEqual(wizard.created_count, 0)
        self.assertFalse(self.Line.search([('witann_bank_movement', '=', 'new')]))

    def test_same_identifier_in_another_journal_is_independent(self):
        number = self._legacy_movement()
        existing = self._line(movement=number)
        other = self.journal.copy({'name': 'Other bank', 'code': 'WIT2', 'bank_account_id': False})
        other.bank_account_id = self.env['res.partner.bank'].create({
            'acc_number': '0000000002', 'partner_id': other.company_id.partner_id.id,
        })
        self._xmlid(number, existing)
        wizard = self._wizard([(number, 100)], journal=other)
        wizard.action_import()
        self.assertEqual(wizard.created_count, 1)
        self.assertEqual(wizard.created_line_ids.journal_id, other)

    def test_legacy_ids_are_verified_without_backfill_or_accounting_writes(self):
        for index in range(2):
            number = self._legacy_movement(index)
            name = number if index == 0 else 'banco_0176055262_' + number
            existing = self._line(movement=False)
            self._xmlid(name, existing)
            before = self._snapshot(existing)
            wizard = self._wizard([(number, 100)])
            with self._forbid_accounting_mutation():
                wizard.action_import()
            self.assertEqual(wizard.created_count, 0)
            self.assertEqual(wizard.existing_count, 1)
            self.assertIn('histórico', wizard.result_ids.message)
            self.assertFalse(existing.witann_bank_movement)
            self.assertEqual(self._snapshot(existing), before)

    def test_legacy_mismatch_and_ambiguous_mapping_are_conflicts(self):
        number = self._legacy_movement()
        first = self._line(movement=False)
        self._xmlid(number, first)
        wizard = self._wizard([(number, 101)])
        wizard.action_import()
        self.assertEqual(wizard.conflict_count, 1)
        second = self._line(movement=False)
        self._xmlid('banco_0176055262_' + number, second)
        wizard = self._wizard([(number, 100)])
        wizard.action_import()
        self.assertEqual(wizard.conflict_count, 1)
        self.assertEqual(wizard.created_count, 0)

    def test_other_model_dangling_xmlid_and_internal_id_are_not_matches(self):
        existing = self._line(movement=False)
        number, stale_number = self._legacy_movement(), self._legacy_movement(1)
        self._xmlid(number, self.partner_a)
        stale = self._xmlid(stale_number, existing)
        stale.res_id = 2147483647  # no such record; do not interpret as a bank ID
        rows = [(number, 100), (stale_number, 100), (str(existing.id), 100)]
        wizard = self._wizard(rows)
        wizard.action_import()
        self.assertEqual(wizard.created_count, 3)
        self.assertTrue(wizard.legacy_warning)

    def test_unverified_prefix_and_same_date_amount_do_not_imply_identity(self):
        number = self._legacy_movement()
        existing = self._line(movement=False)
        self._xmlid(number, existing, module='not_verified')
        wizard = self._wizard([(number, 100)])
        wizard.action_import()
        self.assertEqual(wizard.created_count, 1)
        self.assertTrue(wizard.legacy_warning)

    def _reconciled_fixture(self, movement, settled):
        receivable = self.company_data['default_account_receivable']
        existing = self._line(movement=movement, partner_id=self.partner_a.id, counterpart_account_id=receivable.id)
        move = self.env['account.move'].create({
            'journal_id': self.company_data['default_journal_misc'].id,
            'date': '2026-10-12',
            'line_ids': [
                Command.create({'account_id': receivable.id, 'partner_id': self.partner_a.id, 'debit': settled}),
                Command.create({'account_id': self.company_data['default_account_revenue'].id, 'credit': settled}),
            ],
        })
        move.action_post()
        items = (move.line_ids | existing.move_id.line_ids).filtered(lambda line: line.account_id == receivable)
        items.reconcile()
        self.assertEqual(bool(items.full_reconcile_id), settled == 100)
        self.assertTrue(items.matched_debit_ids | items.matched_credit_ids)
        return existing

    def test_reconciled_move_lines_partial_and_full_reconciliations_unchanged(self):
        for settled in (60, 100):
            movement = 'reconciled-' + str(settled)
            existing = self._reconciled_fixture(movement, settled)
            before = self._snapshot(existing)
            wizard = self._wizard([(movement, 100)])
            with self._forbid_accounting_mutation():
                wizard.action_analyze()
                wizard.action_import()
            self.assertEqual(wizard.created_count, 0)
            self.assertEqual(self._snapshot(existing), before)

    def test_reconciled_legacy_record_is_untouched(self):
        number = self._legacy_movement()
        existing = self._reconciled_fixture(False, 100)
        self._xmlid(number, existing)
        before = self._snapshot(existing)
        wizard = self._wizard([(number, 100)])
        with self._forbid_accounting_mutation():
            wizard.action_import()
        self.assertEqual(wizard.created_count, 0)
        self.assertEqual(self._snapshot(existing), before)

    def test_legacy_multiple_null_identifiers_remain_allowed(self):
        self._line(movement=False)
        self._line(movement=False)
        self.assertGreaterEqual(self.Line.search_count([
            ('journal_id', '=', self.journal.id), ('witann_bank_movement', '=', False),
        ]), 2)

    def test_database_unique_constraint(self):
        self._line()
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self._line()
        self.assertEqual(self.Line.search_count([
            ('journal_id', '=', self.journal.id), ('witann_bank_movement', '=', '31984'),
        ]), 1)

    def test_race_after_lookup_rolls_back_entire_batch_and_cursor_is_usable(self):
        existing = self._line()
        before = self._snapshot(existing)
        wizard = self._wizard([('new-before-collision', 50), ('31984', 100)])
        # Deterministically reproduce a lookup that did not see the other import.
        with patch.object(type(wizard), '_existing', return_value={}):
            with self.assertRaisesRegex(UserError, 'al mismo tiempo'):
                wizard.action_import()
        self.assertFalse(self.Line.search([('witann_bank_movement', '=', 'new-before-collision')]))
        self.assertEqual(self._snapshot(existing), before)
        # A fresh request/lookup safely skips the winner and imports the remainder.
        wizard.action_import()
        self.assertEqual(wizard.created_count, 1)
        self.assertEqual(wizard.skipped_count, 1)

    def test_missing_bank_account_configuration(self):
        self.journal.bank_account_id = False
        wizard = self.Wizard.create({
            'journal_id': self.journal.id, 'filename': 'bank.csv',
            'file_data': base64.b64encode(b'placeholder'),
        })
        with self.assertRaisesRegex(UserError, 'número de cuenta'):
            wizard.action_analyze()

    def test_native_date_adjustment_does_not_silently_change_bank_identity(self):
        wizard = self._wizard([('adjusted-date', 100)])
        native_create = type(self.Line).create

        def shifted_date(model, values):
            return native_create(model, [{**value, 'date': date(2026, 10, 13)} for value in values])

        with patch.object(type(self.Line), 'create', shifted_date):
            with self.assertRaisesRegex(UserError, 'ajustó la fecha'):
                wizard.action_import()
        self.assertFalse(self.Line.search([('witann_bank_movement', '=', 'adjusted-date')]))

    def test_multi_company_and_accountant_without_system_metadata_access(self):
        other_data = self.setup_other_company()
        other = other_data['default_journal_bank']
        other.bank_account_id = self.env['res.partner.bank'].create({
            'acc_number': '0000000003', 'partner_id': other.company_id.partner_id.id,
        })
        number = self._legacy_movement()
        foreign = self._line(journal=other, movement=number)
        self._xmlid(number, foreign)
        accountant = new_test_user(
            self.env, login='witann_bank_accountant',
            groups='account.group_account_user',
            company_id=self.journal.company_id.id,
            company_ids=[Command.set(self.journal.company_id.ids)],
        )
        wizard = self._wizard([(number, 100)], user=accountant)
        wizard.action_import()
        self.assertEqual(wizard.created_count, 1)
        self.assertEqual(wizard.created_line_ids.company_id, self.journal.company_id)
        # Direct RPC with a foreign journal must also fail, beyond the UI domain.
        foreign_wizard = self._wizard([(number, 100)], journal=other)
        with self.assertRaises(AccessError):
            foreign_wizard.with_user(accountant).with_context(
                allowed_company_ids=self.journal.company_id.ids,
            ).action_import()

    def test_hidden_legacy_record_blocks_instead_of_creating_duplicate(self):
        number = self._legacy_movement()
        existing = self._line(movement=False)
        self._xmlid(number, existing)
        accountant = new_test_user(
            self.env, login='witann_restricted_accountant',
            groups='account.group_account_user',
            company_id=self.journal.company_id.id,
            company_ids=[Command.set(self.journal.company_id.ids)],
        )
        self.env['ir.rule'].sudo().create({
            'name': 'Hide fixture bank transaction',
            'model_id': self.env['ir.model']._get_id('account.bank.statement.line'),
            'domain_force': f"[('id', '!=', {existing.id})]",
        })
        wizard = self._wizard([(number, 100)], user=accountant)
        with self.assertRaises(AccessError):
            wizard.action_import()

    def test_280_native_transactions_timing_and_overlap(self):
        rows = [(str(900000 + index), index + 1) for index in range(280)]
        start = time.perf_counter()
        first = self._wizard(rows)
        first.action_import()
        created_seconds = time.perf_counter() - start
        self.assertEqual(first.created_count, 280)
        before = self._snapshot(first.created_line_ids)
        start = time.perf_counter()
        second = self._wizard(rows)
        with self._forbid_accounting_mutation():
            second.action_import()
        skipped_seconds = time.perf_counter() - start
        self.assertEqual(second.created_count, 0)
        self.assertEqual(second.skipped_count, 280)
        self.assertEqual(self._snapshot(first.created_line_ids), before)
        overlap = self._wizard([(str(900000 + index), index + 1) for index in range(140, 420)])
        overlap.action_import()
        self.assertEqual(overlap.created_count, 140)
        self.assertEqual(overlap.skipped_count, 140)
        self.assertEqual(self._snapshot(first.created_line_ids), before)
        _logger.info('WITANN BANK: 280 native creations %.3fs; 280 skips %.3fs (test runtime only)', created_seconds, skipped_seconds)
