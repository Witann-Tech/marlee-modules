from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, new_test_user, tagged
from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged('post_install', '-at_install')
class TestCashVendorReconcile(CommonPosTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'Cash supplier'})
        cls.config = cls.pos_config_usd
        cls.session = cls.env['pos.session'].create({
            'config_id': cls.config.id, 'user_id': cls.env.user.id})
        cls.cash_journal = cls.session.cash_journal_id

    def _bill(self, amount=100, partner=None, company_data=None, **values):
        data = company_data or self.company_data
        bill = self.env['account.move'].with_company(data['company']).create({
            'move_type': 'in_invoice',
            'company_id': data['company'].id,
            'partner_id': (partner or self.vendor).id,
            'invoice_date': fields.Date.today(),
            'journal_id': data['default_journal_purchase'].id,
            'invoice_line_ids': [Command.create({
                'name': 'Supplies', 'quantity': 1, 'price_unit': amount,
                'account_id': data['default_account_expense'].id,
                'tax_ids': [Command.clear()],
            })],
            **values,
        })
        bill.action_post()
        return bill

    def _cash_out(self, amount=100, **values):
        return self.env['account.bank.statement.line'].create({
            'journal_id': self.cash_journal.id,
            'pos_session_id': self.session.id,
            'date': fields.Date.today(), 'amount': -amount,
            'payment_ref': 'Manual cash out for supplies',
            **values,
        })

    def _wizard(self, cash, allocations, partner=None, user=None):
        return self.env['witann.pos.cash.vendor.reconcile'].with_context(
            cash.env.context).with_user(user or self.env.user).create({
            'statement_line_id': cash.id, 'partner_id': (partner or self.vendor).id,
            'line_ids': [Command.create({'bill_id': bill.id, 'amount': amount})
                         for bill, amount in allocations],
        })

    def _branch_cash(self, name, amount=100, company_data=None):
        data = company_data or self.company_data
        root = data['company']
        branch = self.env['res.company'].create({'name': name, 'parent_id': root.id})
        self.env.user.sudo().company_ids |= branch | root
        context = {'allowed_company_ids': [root.id, branch.id]}
        Journal = self.env['account.journal'].with_context(context).with_company(branch)
        cash_journal = Journal.create({
            'name': name + ' Cash', 'type': 'cash',
            'suspense_account_id': data['default_journal_cash'].suspense_account_id.id,
        })
        sale_journal = Journal.create({
            'name': name + ' Sales', 'type': 'sale',
            'default_account_id': data['default_account_revenue'].id,
        })
        method = self.env['pos.payment.method'].with_context(context).with_company(branch).create({
            'name': name + ' Cash', 'company_id': branch.id,
            'journal_id': cash_journal.id,
            'receivable_account_id': data['default_account_receivable'].id,
        })
        config = self.env['pos.config'].with_context(context).with_company(branch).create({
            'name': name + ' POS', 'company_id': branch.id,
            'journal_id': sale_journal.id, 'invoice_journal_id': sale_journal.id,
            'payment_method_ids': [Command.set(method.ids)],
        })
        session = self.env['pos.session'].with_context(context).with_company(branch).create({
            'config_id': config.id, 'user_id': self.env.user.id,
        })
        return self.env['account.bank.statement.line'].with_context(context).with_company(branch).create({
            'journal_id': cash_journal.id, 'pos_session_id': session.id,
            'amount': -amount, 'date': fields.Date.today(), 'payment_ref': name + ' vendor cash out',
        })

    def test_full_payment_reuses_cash_entry_and_keeps_cashier(self):
        bill = self._bill()
        cash = self._cash_out(partner_id=self.partner_mobt.id)
        original = (cash.move_id.id, cash.date, cash.payment_ref, cash.partner_id.id,
                    cash.amount, self.session.cash_register_balance_end)
        liquidity = cash._seek_for_lines()[0]
        liquidity_values = (liquidity.id, liquidity.balance, liquidity.amount_currency)
        move_count = self.env['account.move'].search_count([])
        payment_count = self.env['account.payment'].search_count([])
        self._wizard(cash, [(bill, 100)]).action_reconcile()
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(bill.payment_state, 'paid')
        self.assertEqual(cash.witann_vendor_reconciliation_state, 'reconciled')
        self.assertEqual(cash.witann_vendor_bill_ids, bill)
        self.assertEqual(original, (cash.move_id.id, cash.date, cash.payment_ref, cash.partner_id.id,
                                   cash.amount, self.session.cash_register_balance_end))
        self.assertEqual(liquidity_values, (liquidity.id, liquidity.balance, liquidity.amount_currency))
        self.assertEqual(move_count, self.env['account.move'].search_count([]))
        self.assertEqual(payment_count, self.env['account.payment'].search_count([]))
        self.assertTrue(cash.is_reconciled)

    def test_one_cash_out_multiple_bills_and_partial_payment(self):
        first, second = self._bill(60), self._bill(100)
        cash = self._cash_out()
        self._wizard(cash, [(first, 60), (second, 40)]).action_reconcile()
        self.assertEqual(first.payment_state, 'paid')
        self.assertEqual(second.payment_state, 'partial')
        self.assertEqual(second.amount_residual, 60)
        self.assertEqual(cash.witann_vendor_bill_ids, first | second)
        self.assertEqual(cash.witann_vendor_reconciliation_state, 'reconciled')
        next_cash = self._cash_out(60)
        self._wizard(next_cash, [(second, 60)]).action_reconcile()
        self.assertEqual(second.payment_state, 'paid')
        self.assertEqual(second.amount_residual, 0)

    def test_undo_reopens_only_allocated_amount_and_can_reconcile_again(self):
        bill = self._bill(200)
        first, second = self._cash_out(), self._cash_out()
        self._wizard(first, [(bill, 100)]).action_reconcile()
        self._wizard(second, [(bill, 100)]).action_reconcile()
        first.action_witann_undo_vendor_reconciliation()
        self.assertEqual(bill.amount_residual, 100)
        self.assertEqual(first.witann_vendor_reconciliation_state, 'pending')
        self.assertFalse(first.witann_vendor_bill_ids)
        self.assertEqual(second.witann_vendor_reconciliation_state, 'reconciled')
        self.assertEqual(first.amount, -100)
        self._wizard(first, [(bill, 100)]).action_reconcile()
        self.assertEqual(bill.payment_state, 'paid')

    def test_repeated_submission_cannot_pay_twice(self):
        bill = self._bill(200)
        cash = self._cash_out()
        wizard = self._wizard(cash, [(bill, 100)])
        wizard.action_reconcile()
        with self.assertRaises(UserError), self.cr.savepoint():
            wizard.action_reconcile()
        self.assertEqual(bill.amount_residual, 100)

    def test_duplicate_bill_is_rejected_even_with_sufficient_residual(self):
        bill, cash = self._bill(200), self._cash_out()
        with self.assertRaisesRegex(UserError, 'una sola vez'), self.cr.savepoint():
            self._wizard(cash, [(bill, 50), (bill, 50)]).action_reconcile()
        self.assertEqual(bill.amount_residual, 200)
        self.assertEqual(cash.witann_vendor_reconciliation_state, 'pending')

    def test_already_paid_bill_cannot_be_paid_again(self):
        bill = self._bill()
        self._wizard(self._cash_out(), [(bill, 100)]).action_reconcile()
        cash = self._cash_out()
        with self.assertRaises(UserError), self.cr.savepoint():
            self._wizard(cash, [(bill, 100)]).action_reconcile()
        self.assertEqual(cash.witann_vendor_reconciliation_state, 'pending')

    def test_amount_and_residual_validation_is_atomic(self):
        bill = self._bill(80)
        cash = self._cash_out()
        for allocations in [[], [(bill, 80)], [(bill, 100)], [(bill, 0)],
                            [(bill, -100)], [(bill, 79.999)], [(bill, float('nan'))], [(bill, float('inf'))],
                            [(bill, 30), (bill, 70)]]:
            with self.subTest(allocations=allocations):
                with self.assertRaises(UserError), self.cr.savepoint():
                    cash._witann_reconcile_vendor_bills(allocations)
                self.assertEqual(bill.amount_residual, 80)
                self.assertEqual(cash.witann_vendor_reconciliation_state, 'pending')

    def test_different_suppliers_and_wrong_selected_supplier_rejected(self):
        first = self._bill(50)
        second = self._bill(50, partner=self.partner_mobt)
        cash = self._cash_out()
        with self.assertRaises(UserError), self.cr.savepoint():
            self._wizard(cash, [(first, 50), (second, 50)]).action_reconcile()
        with self.assertRaises(UserError), self.cr.savepoint():
            self._wizard(cash, [(first, 50)], partner=self.partner_mobt).action_reconcile()

    def test_draft_customer_and_foreign_currency_bills_rejected(self):
        draft = self._bill()
        draft.button_draft()
        customer = self._bill(
            move_type='out_invoice', journal_id=self.company_data['default_journal_sale'].id)
        foreign_currency = self.env.ref('base.EUR')
        if foreign_currency == self.env.company.currency_id:
            foreign_currency = self.env.ref('base.USD')
        foreign = self._bill(currency_id=foreign_currency.id)
        cash = self._cash_out()
        for bill in (draft, customer, foreign):
            with self.subTest(bill=bill):
                with self.assertRaises(UserError), self.cr.savepoint():
                    self._wizard(cash, [(bill, 100)]).action_reconcile()
        self.assertEqual(cash.witann_vendor_reconciliation_state, 'pending')

    def test_non_manual_movements_and_cash_in_rejected(self):
        bill = self._bill()
        cash_in = self._cash_out(-100)
        refund = self._cash_out(
            counterpart_account_id=self.company_data['default_account_receivable'].id)
        expense = self._cash_out(
            counterpart_account_id=self.company_data['default_account_expense'].id)
        no_session = self._cash_out(pos_session_id=False)
        for cash in (cash_in, refund, expense, no_session):
            with self.subTest(cash=cash):
                self.assertEqual(cash.witann_vendor_reconciliation_state, 'other')
                with self.assertRaises(UserError), self.cr.savepoint():
                    self._wizard(cash, [(bill, 100)]).action_reconcile()

    def test_reconciled_cash_cannot_be_deleted_by_cashier_flow(self):
        bill, cash = self._bill(), self._cash_out()
        self._wizard(cash, [(bill, 100)]).action_reconcile()
        with self.assertRaises(UserError), self.cr.savepoint():
            cash.sudo().unlink()
        self.assertTrue(cash.exists())
        self.assertEqual(bill.payment_state, 'paid')

    def test_cashier_cannot_open_or_apply_reconciliation(self):
        cashier = new_test_user(self.env, login='cash_reconcile_cashier',
                                groups='point_of_sale.group_pos_user')
        bill, cash = self._bill(), self._cash_out()
        with self.assertRaises(AccessError), self.cr.savepoint():
            cash.with_user(cashier).action_witann_reconcile_vendor()
        with self.assertRaises(AccessError), self.cr.savepoint():
            self._wizard(cash, [(bill, 100)]).with_user(cashier).action_reconcile()

    def test_accountant_without_pos_manager_can_reconcile(self):
        accountant = new_test_user(self.env, login='cash_reconcile_accountant',
                                  groups='account.group_account_user')
        bill, cash = self._bill(), self._cash_out()
        self._wizard(cash, [(bill, 100)], user=accountant).action_reconcile()
        self.assertEqual(bill.payment_state, 'paid')
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.session.with_user(accountant).write({'closing_notes': 'not allowed'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.config.with_user(accountant).write({'name': 'not allowed'})

    def test_cross_company_bill_is_rejected_even_with_both_companies_active(self):
        other_data = self.setup_other_company()
        other_company = other_data['company']
        other_bill = self.env['account.move'].with_company(other_company).create({
            'move_type': 'in_invoice', 'company_id': other_company.id,
            'partner_id': self.vendor.id, 'invoice_date': fields.Date.today(),
            'journal_id': other_data['default_journal_purchase'].id,
            'invoice_line_ids': [Command.create({
                'name': 'Other company supplies', 'price_unit': 100,
                'account_id': other_data['default_account_expense'].id,
                'tax_ids': [Command.clear()],
            })],
        })
        other_bill.action_post()
        cash = self._cash_out().with_context(
            allowed_company_ids=[self.env.company.id, other_company.id])
        with self.assertRaises(UserError), self.cr.savepoint():
            cash._witann_reconcile_vendor_bills([(other_bill, 100)])
        self.assertEqual(other_bill.amount_residual, 100)
        self.assertEqual(cash.witann_vendor_reconciliation_state, 'pending')

    def test_two_branches_can_pay_and_undo_one_parent_bill(self):
        bill = self._bill(200)
        first, second = self._branch_cash('North branch'), self._branch_cash('South branch')
        companies = bill.company_id | first.company_id | second.company_id
        first = first.with_context(allowed_company_ids=companies.ids)
        second = second.with_context(allowed_company_ids=companies.ids)
        first_move, second_move = first.move_id, second.move_id
        first_liquidity = first._seek_for_lines()[0]
        self._wizard(first, [(bill, 100)]).action_reconcile()
        self.assertEqual(bill.amount_residual, 100)
        self.assertEqual(first._seek_for_lines()[0], first_liquidity)
        self._wizard(second, [(bill, 100)]).action_reconcile()
        self.assertEqual(bill.payment_state, 'paid')
        self.assertEqual(bill.company_id, self.env.company)
        self.assertNotEqual(first.company_id, second.company_id)
        self.assertEqual(first.company_id.root_id, bill.company_id)
        self.assertEqual(first.move_id, first_move)
        self.assertEqual(second.move_id, second_move)
        first.action_witann_undo_vendor_reconciliation()
        self.assertEqual(bill.amount_residual, 100)
        self.assertEqual(second.witann_vendor_reconciliation_state, 'reconciled')
        self._wizard(first, [(bill, 100)]).action_reconcile()
        self.assertEqual(bill.payment_state, 'paid')

    def test_branch_form_accepts_supplier_and_bill_owned_by_parent(self):
        self.vendor.company_id = self.env.company
        bill, cash = self._bill(), self._branch_cash('Parent supplier branch')
        with Form(self.env['witann.pos.cash.vendor.reconcile'].with_context(
                cash.env.context, default_statement_line_id=cash.id)) as form:
            self.assertEqual(form.accounting_company_id, bill.company_id)
            form.partner_id = self.vendor
            with form.line_ids.new() as row:
                row.bill_id = bill
                self.assertEqual(row.bill_company_id, bill.company_id)
                self.assertEqual(row.amount, 100)
        form.record.action_reconcile()
        self.assertEqual(bill.payment_state, 'paid')

    def test_branch_rule_also_applies_to_another_independent_company(self):
        data = self.setup_other_company()
        bill = self._bill(company_data=data)
        cash = self._branch_cash('Another group branch', company_data=data)
        self._wizard(cash, [(bill, 100)]).action_reconcile()
        self.assertEqual(bill.payment_state, 'paid')
        self.assertEqual(cash.company_id.root_id, data['company'])
        self.assertNotEqual(cash.company_id.root_id, self.env.company.root_id)

    def test_branch_cannot_pay_another_root_company_bill(self):
        data = self.setup_other_company()
        bill, cash = self._bill(company_data=data), self._branch_cash('Isolated branch')
        cash = cash.with_context(allowed_company_ids=[*cash.env.companies.ids, data['company'].id])
        with self.assertRaisesRegex(UserError, 'empresa matriz'), self.cr.savepoint():
            self._wizard(cash, [(bill, 100)]).action_reconcile()
        self.assertEqual(bill.amount_residual, 100)
        self.assertEqual(cash.witann_vendor_reconciliation_state, 'pending')

    def test_branch_only_accountant_does_not_gain_access_to_parent_bills(self):
        bill, cash = self._bill(), self._branch_cash('Restricted branch')
        accountant = new_test_user(
            self.env, login='cash_branch_accountant', groups='account.group_account_user',
            company_id=cash.company_id.id, company_ids=[Command.set(cash.company_id.ids)])
        restricted_cash = cash.with_context(
            allowed_company_ids=cash.company_id.ids).with_user(accountant)
        with self.assertRaises(AccessError), self.cr.savepoint():
            self._wizard(restricted_cash, [(bill, 100)], user=accountant).action_reconcile()
        self.assertEqual(bill.amount_residual, 100)
        self.assertEqual(cash.witann_vendor_reconciliation_state, 'pending')

    def test_payment_term_installments_are_reconciled(self):
        terms = self.env['account.payment.term'].create({
            'name': 'Two installments',
            'line_ids': [Command.create({'value': 'percent', 'value_amount': 50, 'nb_days': 0}),
                         Command.create({'value': 'percent', 'value_amount': 50, 'nb_days': 30})],
        })
        bill = self._bill(invoice_payment_term_id=terms.id)
        cash = self._cash_out(75)
        self._wizard(cash, [(bill, 75)]).action_reconcile()
        self.assertEqual(bill.amount_residual, 25)
        self.assertEqual(cash.witann_vendor_reconciliation_state, 'reconciled')

    def test_fiscal_lock_rejects_reclassification(self):
        bill, cash = self._bill(), self._cash_out()
        # Odoo forbids locking a period with a suspense transaction. Lock an
        # already reconciled cash entry, then verify that undo respects the lock.
        self._wizard(cash, [(bill, 100)]).action_reconcile()
        cash.company_id.sudo().hard_lock_date = fields.Date.today()
        with self.assertRaises(UserError), self.cr.savepoint():
            cash.action_witann_undo_vendor_reconciliation()
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(cash.witann_vendor_reconciliation_state, 'reconciled')

    def test_wizard_onchange_defaults_amount_and_native_views_validate(self):
        bill = self._bill(150)
        cash = self._cash_out()
        with Form(self.env['witann.pos.cash.vendor.reconcile'].with_context(
                default_statement_line_id=cash.id)) as form:
            form.partner_id = self.vendor
            with form.line_ids.new() as row:
                row.bill_id = bill
                self.assertEqual(row.amount, 100)
            self.assertEqual(form.difference, 0)
        form.record.action_reconcile()
        self.assertEqual(bill.amount_residual, 50)

    def test_native_undo_updates_derived_status(self):
        bill, cash = self._bill(), self._cash_out()
        self._wizard(cash, [(bill, 100)]).action_reconcile()
        cash.action_undo_reconciliation()
        self.assertEqual(cash.witann_vendor_reconciliation_state, 'pending')
        self.assertFalse(cash.witann_vendor_bill_ids)
        self.assertEqual(bill.amount_residual, 100)

    def test_closed_session_is_supported(self):
        bill, cash = self._bill(), self._cash_out()
        self.session.cash_register_balance_end_real = -100
        self.session.action_pos_session_closing_control()
        if self.session.state != 'closed':
            self.session.action_pos_session_close()
        self.assertEqual(self.session.state, 'closed')
        balance_before = self.session.cash_register_balance_end
        self._wizard(cash, [(bill, 100)]).action_reconcile()
        self.assertEqual(bill.payment_state, 'paid')
        self.assertEqual(balance_before, self.session.cash_register_balance_end)
