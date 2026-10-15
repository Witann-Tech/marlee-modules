"""Run the real lifecycle adapter against an isolated native-engine double.

These verify ownership, delegation and scope; actual Enterprise ORM/SQL and
transaction behavior remain covered by the staging integration gate.
"""

import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / 'witann_group_subscriptions_pos/models/subscription_lifecycle.py'
BASE_FILE = ROOT / 'witann_group_subscriptions/models/subscription_lifecycle.py'
CONTEXT = 'wgs_native_subscription_lifecycle'


class Domain:
    def __init__(self, *values):
        if len(values) == 3:
            self.tree = ('atom', *values)
        elif isinstance(values[0], Domain):
            self.tree = values[0].tree
        else:
            self.tree = ('all', [Domain(*item).tree for item in values[0]])

    def _combine(self, operator, other=None):
        result = Domain([])
        result.tree = (operator, self.tree, other.tree) if other is not None else (operator, self.tree)
        return result

    def __and__(self, other):
        return self._combine('and', Domain(other))

    def __or__(self, other):
        return self._combine('or', Domain(other))

    def __invert__(self):
        return self._combine('not')

    def matches(self, row):
        def evaluate(tree, record):
            operator = tree[0]
            if operator == 'all':
                return all(evaluate(item, record) for item in tree[1])
            if operator == 'and':
                return evaluate(tree[1], record) and evaluate(tree[2], record)
            if operator == 'or':
                return evaluate(tree[1], record) or evaluate(tree[2], record)
            if operator == 'not':
                return not evaluate(tree[1], record)
            _, name, comparison, value = tree
            actual = record
            for part in name.split('.'):
                actual = actual[part]
            if comparison == 'any':
                return any(value.matches(child) for child in actual)
            if comparison == '=':
                return not bool(actual) if value is False else actual == value
            if comparison == '!=':
                return bool(actual) if value is False else actual != value
            if comparison == 'in':
                return actual in value
            if comparison == '>':
                return actual > value
            raise AssertionError(comparison)
        return evaluate(self.tree, row)


class Env:
    def __init__(self, model, context):
        self.model, self.context = model, context

    def __getitem__(self, model_name):
        assert model_name == 'sale.order'
        return self.model.browse([])


class NativeBase:
    def __init__(self, rows, ids=(), context=None, stats=None):
        self.rows, self.ids = rows, list(ids)
        self.stats = stats if stats is not None else {}
        self.env = Env(self, context or {})

    def __bool__(self):
        return bool(self.ids)

    def browse(self, ids):
        return type(self)(self.rows, ids, self.env.context, self.stats)

    def with_context(self, **values):
        return type(self)(self.rows, self.ids, {**self.env.context, **values}, self.stats)

    def filtered_domain(self, domain):
        return self.browse([key for key in self.ids if Domain(domain).matches(self.rows[key])])

    def _search(self, domain, *args, **kwargs):
        self.stats['last_search_args'] = (args, kwargs)
        self.stats['searches'] = self.stats.get('searches', 0) + 1
        ids = [key for key, row in self.rows.items() if Domain(domain).matches(row)]
        offset = args[0] if args else kwargs.get('offset', 0)
        limit = args[1] if len(args) > 1 else kwargs.get('limit')
        return ids[offset:offset + limit] if limit is not None else ids[offset:]

    def search(self, domain, *args, **kwargs):
        return self.browse(self._search(domain, *args, **kwargs))

    def _recurring_invoice_domain(self, extra_domain=None):
        return Domain([('eligible', '=', True)]) & Domain(extra_domain or [])

    def _recurring_invoice_get_subscriptions(self, grouped=False, batch_size=30):
        self.stats['invoice_selection_called'] = True
        self.stats['invoice_selection_args'] = (grouped, batch_size)
        return (self if self else self.search(self._recurring_invoice_domain())), False

    def _subscription_reminder_parameters(self):
        return {'domain': [('eligible', '=', True)], 'next_invoice_dates': {'unchanged'}}

    def _get_expired_subscriptions(self):
        return [{'so_id': key, 'native_data': 'expiry'} for key in self.rows]

    def _get_unpaid_subscriptions(self):
        return [{'so_id': key, 'am_id': key + 100} for key in self.rows]

    def set_close(self, close_reason_id=None, renew=False):
        for key in self.ids:
            self.rows[key]['closed'] = True
        return True

    def _subscription_auto_close(self):
        self.set_close()
        return self

    def _cron_recurring_create_invoice(self):
        selected, _retrigger = self._recurring_invoice_get_subscriptions()
        for key in selected.ids:
            self.rows[key]['billed'] = True
        selected._subscription_auto_close()
        return selected.ids

    def _cron_subscription_expiration(self):
        # Native expiry unions ORM selections and raw-SQL candidate IDs.
        ids = set(self.search([('eligible', '=', True)]).ids)
        ids.update(row['so_id'] for row in self._get_expired_subscriptions())
        ids.update(row['so_id'] for row in self._get_unpaid_subscriptions())
        self.browse(sorted(ids)).set_close()
        return {'closed': sorted(ids)}

    def _cron_recurring_send_payment_reminder(self):
        parameters = self._subscription_reminder_parameters()
        selected = self.search(parameters['domain'])
        for key in selected.ids:
            self.rows[key]['reminded'] = True
        selected.set_close()
        return selected.ids


def adapter_class():
    namespace = {'NativeBase': NativeBase, 'Domain': Domain}
    parent = 'NativeBase'
    for file in (BASE_FILE, FILE):
        tree = ast.parse(file.read_text())
        node = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        node.bases = [ast.Name(id=parent, ctx=ast.Load())]
        node.body = [item for item in node.body if isinstance(item, ast.FunctionDef) or (
            isinstance(item, ast.Assign) and isinstance(item.value, ast.Constant)
        )]
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                item.decorator_list = []
        ast.fix_missing_locations(node)
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(file), 'exec'), namespace)
        parent = node.name
    return namespace['SaleOrderWgsLifecycle'], namespace[parent]


BaseAdapter, Adapter = adapter_class()


def fixture():
    def payment(state, qty=1):
        return {'order_id': {'state': state}, 'qty': qty, 'wgs_subscription_flow': 'new'}
    rows = {key: {'id': key, 'eligible': True, 'wgs_pos_applied_line_ids': [],
                  'wgs_subscription_operation_line_ids': [], 'wgs_access_site_ids': [],
                  'wgs_domiciliation_contract_id': False} for key in range(1, 10)}
    rows[1]['wgs_pos_applied_line_ids'] = [payment('done')]
    rows[2]['wgs_subscription_operation_line_ids'] = [payment('paid')]
    rows[4]['wgs_pos_applied_line_ids'] = [payment('draft')]
    rows[5]['wgs_pos_applied_line_ids'] = [payment('paid', -1)]
    rows[6]['wgs_pos_applied_line_ids'] = [payment('paid')]
    rows[7]['wgs_access_site_ids'] = [2]
    rows[8]['wgs_domiciliation_contract_id'] = 8
    rows[9]['wgs_pos_applied_line_ids'] = [{**payment('paid'), 'wgs_subscription_flow': 'pending_charge'}]
    return Adapter(rows)


class LifecycleTests(unittest.TestCase):
    def test_ownership_comes_from_paid_links_including_scheduled_and_free_sales(self):
        model = fixture()
        owned = model.search(model._wgs_managed_subscription_domain())
        self.assertEqual(owned.ids, [1, 2, 6, 7, 8])
        model.rows[4]['wgs_pos_applied_line_ids'][0]['order_id']['state'] = 'paid'
        self.assertEqual(model.search(model._wgs_managed_subscription_domain()).ids, [1, 2, 4, 6, 7, 8])

    def test_all_three_native_jobs_leave_wgs_records_unchanged(self):
        for job in ('_cron_recurring_create_invoice', '_cron_subscription_expiration', '_cron_recurring_send_payment_reminder'):
            with self.subTest(job=job):
                model = fixture()
                before = deepcopy(model.rows)
                getattr(model, job)()
                for key in (1, 2, 6, 7, 8):
                    self.assertEqual(model.rows[key], before[key])
                for key in (3, 4, 5, 9):
                    self.assertTrue(model.rows[key]['closed'])
                self.assertEqual(model.env.context, {})

    def test_automatic_search_filters_before_limit_and_preserves_native_arguments(self):
        model = fixture().with_context(**{CONTEXT: True})
        result = model.search([], 0, 1, 'id', active_test=False, bypass_access=True)
        self.assertEqual(result.ids, [3])
        self.assertEqual(model.stats['last_search_args'], ((0, 1, 'id'), {'active_test': False, 'bypass_access': True}))
        self.assertEqual(fixture().search([]).ids, list(range(1, 10)))

    def test_empty_explicit_invoice_batch_does_not_expand_to_other_subscriptions(self):
        model = fixture().with_context(**{CONTEXT: True})
        self.assertEqual(model.browse([1, 2, 6])._recurring_invoice_get_subscriptions(), ([], False))
        self.assertNotIn('invoice_selection_called', model.stats)
        native, retrigger = model.browse([1, 3])._recurring_invoice_get_subscriptions(grouped=True, batch_size=7)
        self.assertEqual(native.ids, [3])
        self.assertFalse(retrigger)
        self.assertEqual(model.stats['invoice_selection_args'], (True, 7))

    def test_manual_closing_still_works_and_automatic_explicit_batches_are_guarded(self):
        model = fixture()
        model.browse([1]).set_close()
        self.assertTrue(model.rows[1]['closed'])
        model.with_context(**{CONTEXT: True}).browse([2, 3]).set_close()
        self.assertNotIn('closed', model.rows[2])
        self.assertTrue(model.rows[3]['closed'])
        self.assertEqual(fixture().browse([1, 3])._subscription_auto_close().ids, [3])

    def test_raw_sql_rows_are_filtered_in_one_lookup_without_altering_native_data(self):
        model = fixture().with_context(**{CONTEXT: True})
        rows = [{'so_id': key, 'am_id': key + 100} for key in range(1, 10)]
        before = deepcopy(rows)
        self.assertEqual(model._wgs_filter_native_expiration_rows(rows), [rows[2], rows[3], rows[4], rows[8]])
        self.assertEqual(model.stats['searches'], 1)
        self.assertEqual(rows, before)
        self.assertIs(fixture()._wgs_filter_native_expiration_rows(rows), rows)

    def test_invoice_and_reminder_domains_preserve_extra_conditions(self):
        model = fixture()
        self.assertEqual(model.search(model._recurring_invoice_domain([('id', 'in', [1, 3])])).ids, [3])
        parameters = model._subscription_reminder_parameters()
        self.assertEqual(model.search(parameters['domain']).ids, [3, 4, 5, 9])
        self.assertEqual(parameters['next_invoice_dates'], {'unchanged'})

    def test_backend_access_and_domiciliation_are_protected_without_pos_installed(self):
        rows = fixture().rows
        model = BaseAdapter(rows)
        model._cron_subscription_expiration()
        self.assertNotIn('closed', rows[7])
        self.assertNotIn('closed', rows[8])
        self.assertTrue(rows[3]['closed'])
