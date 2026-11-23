"""Run only via odoo shell in the disposable database created by the local gate."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from psycopg2.errors import SerializationFailure

from odoo import api, Command, fields
from odoo.exceptions import UserError
from odoo.tests import new_test_user


if os.environ.get('POS_CASH_DISPOSABLE_TEST') != '1' or env.cr.dbname != 'pos_cash_qa':
    raise RuntimeError('This gate requires the isolated pos_cash_qa database.')

company = env.company
company.country_id = env.ref('base.us')
company.account_fiscal_country_id = env.ref('base.us')
currency = company.currency_id


def account(code, account_type, reconcile=False):
    return env['account.account'].create({
        'name': 'Cash concurrency ' + code, 'code': code,
        'account_type': account_type, 'reconcile': reconcile,
        'company_ids': [Command.set(company.ids)],
    })


payable = account('QACASH01', 'liability_payable', True)
receivable = account('QACASH02', 'asset_receivable', True)
expense = account('QACASH03', 'expense')
revenue = account('QACASH04', 'income')
suspense = account('QACASH05', 'asset_current', True)
cash_account = account('QACASH06', 'asset_cash')
company.account_default_pos_receivable_account_id = receivable
sale_journal = env['account.journal'].create({
    'name': 'QA cash sales', 'code': 'QACSL', 'type': 'sale',
    'default_account_id': revenue.id,
})
purchase_journal = env['account.journal'].create({
    'name': 'QA cash purchases', 'code': 'QACPU', 'type': 'purchase',
    'default_account_id': expense.id,
})
cash_journal = env['account.journal'].create({
    'name': 'QA cash drawer', 'code': 'QACSH', 'type': 'cash',
    'default_account_id': cash_account.id, 'suspense_account_id': suspense.id,
})
payment_method = env['pos.payment.method'].create({
    'name': 'QA cash', 'journal_id': cash_journal.id,
    'receivable_account_id': receivable.id,
})
config = env['pos.config'].create({
    'name': 'QA concurrent drawer', 'journal_id': sale_journal.id,
    'invoice_journal_id': sale_journal.id,
    'payment_method_ids': [Command.set(payment_method.ids)],
})
session = env['pos.session'].create({'config_id': config.id, 'user_id': env.user.id})
vendor = env['res.partner'].create({
    'name': 'QA concurrent supplier', 'property_account_payable_id': payable.id,
    'property_account_receivable_id': receivable.id,
})


def bill():
    record = env['account.move'].create({
        'move_type': 'in_invoice', 'partner_id': vendor.id,
        'invoice_date': fields.Date.today(), 'journal_id': purchase_journal.id,
        'invoice_line_ids': [Command.create({
            'name': 'QA supplies', 'price_unit': 100, 'quantity': 1,
            'account_id': expense.id, 'tax_ids': [Command.clear()],
        })],
    })
    record.action_post()
    return record


def cash_out():
    return env['account.bank.statement.line'].create({
        'journal_id': cash_journal.id, 'pos_session_id': session.id,
        'amount': -100, 'date': fields.Date.today(), 'payment_ref': 'QA concurrent cash out',
    })


registry = env.registry
company_id = company.id
worker_user_id = new_test_user(
    env, login='qa_cash_workers', groups='account.group_account_user',
    company_id=company_id).id


def race(targets):
    barrier = Barrier(2)

    def worker(target):
        cash_id, bill_id = target
        serialization_failures = 0
        for attempt in range(3):
            with registry.cursor() as cr:
                worker_env = api.Environment(cr, worker_user_id, {'allowed_company_ids': [company_id]})
                cash = worker_env['account.bank.statement.line'].browse(cash_id)
                invoice = worker_env['account.move'].browse(bill_id)
                # Both workers must read the same old database snapshot first.
                assert cash.witann_vendor_reconciliation_state == 'pending' or attempt
                _ = invoice.amount_residual
                if attempt == 0:
                    barrier.wait(timeout=20)
                try:
                    cash._witann_reconcile_vendor_bills([(invoice, 100)])
                    cr.commit()
                    return 'paid', serialization_failures
                except SerializationFailure:
                    cr.rollback()
                    serialization_failures += 1
                except UserError as error:
                    cr.rollback()
                    return 'rejected', serialization_failures, str(error)
        raise AssertionError('Serialization retry budget exhausted')

    env.cr.commit()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, targets))
    assert sorted(result[0] for result in results) == ['paid', 'rejected'], results
    assert sum(result[1] for result in results) >= 1, results
    env.invalidate_all()
    return results


first_cash, first_bill, second_bill = cash_out(), bill(), bill()
print('Same cash out, different bills:', race([
    (first_cash.id, first_bill.id), (first_cash.id, second_bill.id)]))
assert sorted([first_bill.amount_residual, second_bill.amount_residual]) == [0, 100]
assert first_cash.witann_vendor_reconciliation_state == 'reconciled'

third_bill, second_cash, third_cash = bill(), cash_out(), cash_out()
print('Different cash outs, same bill:', race([
    (second_cash.id, third_bill.id), (third_cash.id, third_bill.id)]))
assert third_bill.amount_residual == 0
assert sorted([second_cash.witann_vendor_reconciliation_state,
               third_cash.witann_vendor_reconciliation_state]) == ['pending', 'reconciled']
print('PASS: concurrent requests cannot reuse cash or overpay a bill.')
