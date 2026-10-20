"""Execute the actual application assertions with isolated native records.

These tests exercise failure paths locally; the addon ORM suite remains the
integration gate for transactions, constraints, SQL queues and native hooks.
"""

from contextlib import closing
from datetime import date
import json
import sqlite3
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock

from test_subscription_contract import contract, method, OPS, POS, UserError


APPLICATION = 'witann_group_subscriptions_pos/models/subscription_application.py'
ADAPTER = 'witann_group_subscriptions_pos/models/subscription_native_adapter.py'


class Lines(list):
    def filtered(self, predicate):
        return Lines(item for item in self if predicate(item))

    def flush_recordset(self):
        pass

    def __getattr__(self, key):
        if len(self) == 1:
            return getattr(self[0], key)
        raise AttributeError(key)


def fixture():
    product = SimpleNamespace(id=20, recurring_invoice=True, uom_id=SimpleNamespace(id=1))
    holder, company = object(), object()
    currency = SimpleNamespace(compare_amounts=lambda a, b: round(a - b, 2))
    subscription = SimpleNamespace(
        ensure_one=lambda: None, flush_recordset=lambda: None, invalidate_recordset=lambda names: None,
        company_id=company, partner_id=holder, currency_id=currency, plan_id=SimpleNamespace(id=3),
        order_line=Lines([SimpleNamespace(product_id=product, product_uom_qty=1, price_unit=619, discount=0)]),
        participant_ids=SimpleNamespace(ids=[8]), end_date=date(2026, 11, 14),
        next_invoice_date=date(2026, 11, 15), wgs_monthly_cutoff_day=14,
        wgs_effective_start_date=date(2026, 10, 14), start_date=date(2026, 10, 14),
    )
    line = SimpleNamespace(
        qty=1, price_unit=619, product_id=product, wgs_subscription_flow='reenroll',
        wgs_application_state=False, wgs_subscription_source_id=subscription,
    )
    pricing = {
        'plan_id': 3, 'price_unit': 619, 'subscription_start_date': date(2026, 10, 14),
        'subscription_end_date': date(2026, 11, 14), 'next_billing_date': date(2026, 11, 15),
        'monthly_cutoff_day': 14, 'snapshot': {'ticket_charge_now': 619, 'commercial_quote': {'signature': 'signed'}},
    }
    owner = SimpleNamespace(
        company_id=company, partner_id=holder, currency_id=currency,
        _wgs_resolve_subscription_participant_ids_for_pos_line=lambda **kw: [8],
        _wgs_source_revision=lambda record: 'unchanged',
    )
    owner._wgs_assert_subscription_application = MethodType(method(APPLICATION, '_wgs_assert_subscription_application'), owner)
    owner._wgs_assert_domiciliation_application = MethodType(method(APPLICATION, '_wgs_assert_domiciliation_application'), owner)
    return owner, line, subscription, pricing


class ApplicationTests(unittest.TestCase):
    def test_exact_native_result_is_accepted(self):
        owner, line, subscription, pricing = fixture()
        owner._wgs_assert_subscription_application(line, subscription, pricing, before=False)

    def test_wrong_plan_product_dates_price_participants_or_owner_are_rejected(self):
        mutations = (
            lambda s: setattr(s.plan_id, 'id', 1),
            lambda s: setattr(s.order_line[0], 'product_id', SimpleNamespace(id=21, recurring_invoice=True)),
            lambda s: setattr(s, 'end_date', date(2026, 10, 15)),
            lambda s: setattr(s, 'next_invoice_date', date(2026, 11, 14)),
            lambda s: setattr(s, 'wgs_monthly_cutoff_day', 0),
            lambda s: setattr(s.order_line[0], 'price_unit', 393.79),
            lambda s: setattr(s.order_line[0], 'discount', 100),
            lambda s: setattr(s.order_line[0], 'product_uom_qty', 2),
            lambda s: setattr(s.participant_ids, 'ids', [8, 9]),
            lambda s: setattr(s, 'partner_id', object()),
            lambda s: setattr(s, 'company_id', object()),
            lambda s: setattr(s, 'wgs_effective_start_date', date(2026, 10, 15)),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                owner, line, subscription, pricing = fixture()
                mutate(subscription)
                with self.assertRaises(UserError):
                    owner._wgs_assert_subscription_application(line, subscription, pricing, before=False)

    def test_future_purchase_keeps_current_package_until_activation(self):
        owner, line, subscription, pricing = fixture()
        line.wgs_application_state = 'scheduled'
        line.wgs_application_date = pricing['subscription_start_date']
        subscription.plan_id.id = 1
        subscription.end_date = date(2026, 10, 13)
        owner._wgs_assert_subscription_application(line, subscription, pricing, before='unchanged')
        with self.assertRaises(UserError):
            owner._wgs_assert_subscription_application(line, subscription, pricing, before='changed')
        with self.assertRaises(UserError):
            owner._wgs_assert_subscription_application(line, subscription, pricing, before='unchanged', activation=True)

    def test_domiciliation_checks_selected_paid_installments_not_ordinary_period(self):
        owner, line, subscription, pricing = fixture()
        contract = SimpleNamespace(
            state='active', subscription_id=subscription, company_id=owner.company_id,
            partner_id=owner.partner_id, product_id=line.product_id, plan_id=subscription.plan_id,
            currency_id=subscription.currency_id, monthly_amount=619,
            access_start_date=pricing['subscription_start_date'],
            installment_ids=Lines([SimpleNamespace(sequence=1, state='paid', paid_pos_line_id=line)]),
        )
        subscription.wgs_domiciliation_contract_id = contract
        pricing['snapshot']['domiciliation'] = {
            'is_domiciliation': True, 'selected_installment_sequences': [1], 'selection_mode': 'initial',
        }
        subscription.end_date = date(2026, 10, 31)
        owner._wgs_assert_subscription_application(line, subscription, pricing, before=False)
        contract.installment_ids[0].paid_pos_line_id = object()
        with self.assertRaises(UserError):
            owner._wgs_assert_subscription_application(line, subscription, pricing, before=False)

    def test_native_adapter_never_writes_related_plan_or_recurring_discount(self):
        owner, line, _subscription, pricing = fixture()
        line.full_product_name = 'Package'
        values = method(ADAPTER, '_wgs_build_subscription_recurring_line_values_for_pos')(
            owner, pos_line=line, product=line.product_id, qty=1,
            recurring_price_unit=pricing['price_unit'],
        )
        self.assertEqual(values['price_unit'], 619)
        self.assertEqual(values['discount'], 0)
        self.assertFalse({'plan_id', 'subscription_plan_id', 'subscription_pricing_id'} & values.keys())

    def test_deferred_activation_must_preserve_original_operation_hash(self):
        owner = Mock()
        line = Mock(qty=1, wgs_subscription_flow='renewal', wgs_application_state='scheduled', wgs_application_hash='stale')
        owner._wgs_line_operation_input.return_value = {'price': 619}
        with self.assertRaises(UserError):
            method(OPS, '_wgs_apply_subscription_operation')(owner, line, activation=True)
        owner._wgs_dispatch_subscription_operation.assert_not_called()

    def test_immediate_and_deferred_application_share_postconditions(self):
        for activation in (False, True):
            with self.subTest(activation=activation):
                owner, line, subscription, pricing = fixture()
                owner.ensure_one = lambda: None
                line.ensure_one = lambda: None
                line.wgs_subscription_flow = 'renewal'
                line.wgs_application_state = 'scheduled' if activation else False
                owner._wgs_line_operation_input = lambda item: {'price': 619}
                line.wgs_application_hash = contract.fingerprint({'price': 619})
                owner._wgs_get_persisted_subscription_pricing_from_pos_line = lambda item: pricing
                owner._wgs_dispatch_subscription_operation = lambda item, **kw: subscription
                owner._wgs_assert_subscription_application = Mock()
                result = method(OPS, '_wgs_apply_subscription_operation')(owner, line, activation=activation)
                self.assertIs(result, subscription)
                owner._wgs_assert_subscription_application.assert_called_once()

    def test_application_rejects_wrong_ticket_price_before_dispatch(self):
        owner, line, _subscription, pricing = fixture()
        owner.ensure_one = lambda: None
        line.ensure_one = lambda: None
        line.price_unit = 393.79
        owner._wgs_get_persisted_subscription_pricing_from_pos_line = lambda item: pricing
        owner._wgs_dispatch_subscription_operation = Mock()
        with self.assertRaises(UserError):
            method(OPS, '_wgs_apply_subscription_operation')(owner, line)
        owner._wgs_dispatch_subscription_operation.assert_not_called()

    def test_signed_pricing_read_never_prefers_redundant_plan_or_live_catalog(self):
        owner, line, _subscription, pricing = fixture()
        signed_pricing = {
            'plan_id': 3, 'pricing_id': False, 'recurring_price': 619,
            'subscription_start_date': '2026-10-14', 'subscription_end_date': '2026-11-14',
            'next_billing_date': '2026-11-15', 'ticket_charge_now': 619,
        }
        owner.env = MagicMock()
        owner.partner_id = SimpleNamespace(id=8)
        owner.company_id = SimpleNamespace(id=10)
        owner.ensure_one = lambda: None
        owner._wgs_to_int = lambda value: int(value or 0)
        owner._wgs_verify_commercial_quote = Mock(return_value={'pricing': signed_pricing})
        owner._wgs_resolve_plan_record = Mock()
        line.ensure_one = lambda: None
        line.wgs_subscription_flow = 'new'
        line.wgs_subscription_source_id = MagicMock(id=False)
        line.wgs_subscription_source_id.__bool__.return_value = False
        line.wgs_pricing_snapshot_json = '{"commercial_quote": {"signature": "signed"}}'
        line.wgs_subscription_plan_id = 1
        line.wgs_subscription_pricing_id = 99
        read = method(POS, '_wgs_get_persisted_subscription_pricing_from_pos_line')
        result = read(owner, line)
        self.assertEqual(result['plan_id'], 3)
        self.assertFalse(result['pricing_id'])
        self.assertEqual(result['price_unit'], 619)
        owner._wgs_resolve_plan_record.assert_not_called()
        owner.env['sale.subscription.plan'].browse.return_value.exists.return_value = False
        with self.assertRaises(UserError):
            read(owner, line)

    def test_refund_postconditions_require_cancelled_contract_and_no_pending_changes(self):
        owner = SimpleNamespace(env=MagicMock())
        subscription = SimpleNamespace(id=7, state='cancel', wgs_domiciliation_contract_id=False)
        owner.env['pos.order.line'].search.return_value = False
        check = method(APPLICATION, '_wgs_assert_subscription_refund')
        check(owner, subscription)
        subscription.wgs_domiciliation_contract_id = SimpleNamespace(state='active')
        with self.assertRaises(UserError):
            check(owner, subscription)
        subscription.wgs_domiciliation_contract_id.state = 'cancelled'
        owner.env['pos.order.line'].search.return_value = object()
        with self.assertRaises(UserError):
            check(owner, subscription)

    def test_activation_budget_is_shared_by_successive_queue_heads(self):
        first, second, unrelated = (SimpleNamespace(id=value) for value in (1, 2, 3))
        batches = [[first, unrelated], [second]]
        calls = []
        def select(today, limit, exclude_ids):
            calls.append(limit)
            self.assertEqual(exclude_ids, [] if len(calls) == 1 else [1, 3])
            return batches.pop(0) if batches else []
        owner = SimpleNamespace(
            _wgs_get_subscription_business_today_for_pos=lambda: date(2026, 10, 14),
            _wgs_select_due_package_changes=select,
            _wgs_activate_package_change=lambda line: line is not unrelated,
        )
        applied = method(OPS, '_wgs_apply_due_package_changes')(owner, limit=3)
        self.assertEqual(applied, 2)
        self.assertEqual(calls, [3, 1])

    def test_nonprogressing_activation_is_still_bounded(self):
        owner = Mock()
        owner._wgs_select_due_package_changes.return_value = [SimpleNamespace(id=1)]
        owner._wgs_activate_package_change.return_value = False
        self.assertEqual(method(OPS, '_wgs_apply_due_package_changes')(owner, limit=2), 0)
        self.assertEqual(owner._wgs_activate_package_change.call_count, 2)

    def test_queue_sql_selects_only_unblocked_paid_heads_before_limiting(self):
        # Execute the actual selector SQL. SQLite supports the same row-value
        # comparison used here; PostgreSQL/ORM locking remains an integration test.
        with closing(sqlite3.connect(':memory:')) as connection, closing(connection.cursor()) as cursor:
            connection.executescript('''
                CREATE TABLE pos_order (id INTEGER PRIMARY KEY, state TEXT);
                CREATE TABLE pos_order_line (
                    id INTEGER PRIMARY KEY, order_id INTEGER,
                    wgs_subscription_source_id INTEGER, wgs_application_date TEXT,
                    wgs_application_state TEXT, wgs_activation_retry_at TEXT
                );
                INSERT INTO pos_order VALUES (1, 'paid'), (2, 'draft');
                INSERT INTO pos_order_line VALUES
                    (1, 1, 10, '2026-08-01', 'review', NULL),
                    (2, 1, 10, '2026-09-01', 'scheduled', NULL),
                    (3, 1, 20, '2026-09-01', 'scheduled', NULL),
                    (4, 1, 20, '2026-10-01', 'scheduled', NULL),
                    (5, 2, 30, '2026-08-01', 'scheduled', NULL),
                    (6, 1, 40, '2026-11-01', 'scheduled', NULL),
                    (7, 1, 30, '2026-10-01', 'scheduled', NULL);
            ''')
            line_model = Mock()
            line_model.sudo.return_value = line_model
            line_model.browse.side_effect = lambda ids: ids
            owner = SimpleNamespace(env=Mock())
            owner.env.__getitem__ = Mock(return_value=line_model)
            def execute(sql, params):
                # Translate only PostgreSQL's array exclusion, not queue logic.
                sql = sql.replace('candidate.id != ALL(%s)',
                                  'candidate.id NOT IN (SELECT value FROM json_each(%s))')
                cursor.execute(sql.replace('%s', '?'), [params[0], str(params[1]), json.dumps(params[2]), params[3]])
            owner.env.cr.execute.side_effect = execute
            owner.env.cr.fetchall.side_effect = cursor.fetchall
            select = method(OPS, '_wgs_select_due_package_changes')
            self.assertEqual(select(owner, '2026-10-14', 1), [1])
            self.assertEqual(select(owner, '2026-10-14', 10), [1, 3, 7])
            self.assertEqual(select(owner, '2026-10-14', 1, exclude_ids=[1]), [3])
            cursor.execute("UPDATE pos_order_line SET wgs_activation_retry_at = '2026-10-14 12:15:00' WHERE id = 1")
            self.assertEqual(select(owner, '2026-10-14', 1), [3])
            cursor.execute("UPDATE pos_order_line SET wgs_application_state = 'applied' WHERE id = 3")
            self.assertEqual(select(owner, '2026-10-14', 1), [4])
            cursor.execute("UPDATE pos_order_line SET wgs_application_state = 'applied' WHERE id = 4")
            cursor.execute("UPDATE pos_order_line SET wgs_activation_retry_at = '2026-10-14 11:00:00' WHERE id = 1")
            # Untouched contracts progress before an old failure is retried.
            self.assertEqual(select(owner, '2026-10-14', 1), [7])
