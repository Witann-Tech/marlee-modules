"""Pure contracts and actual ORM method bodies with isolated collaborators.

Run without Odoo. These do not substitute the addon TransactionCase suite.
"""
import ast
import copy
from datetime import date, timedelta
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from dateutil.relativedelta import relativedelta

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('commercial_contract', ROOT / 'witann_group_subscriptions_pos/subscription_contract.py')
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)

class UserError(Exception):
    pass

class Dates:
    @staticmethod
    def to_date(value):
        if not value:
            return False
        return date.fromisoformat(value) if isinstance(value, str) else value

    @staticmethod
    def to_string(value):
        return value.isoformat() if value else False


def method(file, name):
    tree = ast.parse((ROOT / file).read_text())
    found = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(found) == 1, name
    node = found[0]
    node.decorator_list = []
    ns = {'fields': SimpleNamespace(Date=Dates), 'UserError': UserError, '_': lambda value: value,
          'RULES_VERSION': contract.RULES_VERSION, 'hmac': hmac, 'hashlib': hashlib,
          'canonical_json': contract.canonical_json, 'fingerprint': contract.fingerprint,
          'json': json, 'timedelta': timedelta, 'period': contract.period, 'relativedelta': relativedelta}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(file), 'exec'), ns)
    return ns[name]

POS = 'witann_group_subscriptions_pos/models/pos_order.py'
OPS = 'witann_group_subscriptions_pos/models/subscription_operation.py'

class ContractTests(unittest.TestCase):
    def test_package_change_quotes_target_term_after_source_paid_period(self):
        pricing_file = 'witann_group_subscriptions_pos/models/pos_order_pricing.py'
        build = method(pricing_file, '_wgs_build_subscription_product_renewal_snapshot')
        schedule = method(pricing_file, '_wgs_get_subscription_renewal_schedule')
        sale_schedule = method(pricing_file, '_wgs_get_sale_period_schedule')
        fixed_monthly = method(pricing_file, '_wgs_uses_fixed_monthly_cutoff')
        interval = method(pricing_file, '_wgs_extract_interval_from_plan')
        source, product = Mock(), Mock()
        source.id, source.name = 1303, 'Semester source'
        source._fields = {}
        source.wgs_monthly_cutoff_day = 0
        # Odoo slices return a recordset that still exposes fields.
        class Lines(list):
            @property
            def product_id(self):
                return self[0].product_id

            def __getitem__(self, key):
                value = super().__getitem__(key)
                return Lines(value) if isinstance(key, slice) else value

        source.order_line.filtered.return_value.sorted.return_value = Lines([Mock()])
        for unit, expected_end in [('day', '2026-11-14'), ('month', '2026-12-14')]:
            with self.subTest(target_unit=unit):
                plan = SimpleNamespace(
                    _fields={'billing_period_value', 'billing_period_unit'},
                    billing_period_value=1, billing_period_unit=unit, ensure_one=lambda: None,
                )
                owner = Mock()
                owner._wgs_build_product_pricing_snapshot.return_value = {
                    'plan_id': 9, 'pricing_id': False, 'price_unit': 688.79,
                    'display_price_unit': 799.0,
                }
                owner._wgs_resolve_plan_record.return_value = plan
                owner._wgs_get_subscription_business_today_for_pos.return_value = date(2026, 9, 28)
                owner._wgs_get_first_date_from_order.side_effect = [date(2026, 11, 14), date(2026, 11, 13)]
                source._wgs_normalize_next_invoice_date_for_access.side_effect = lambda next_date, end: next_date
                owner._wgs_pending_package_changes.return_value = []
                owner._wgs_should_align_plan_to_calendar_month.return_value = False
                owner._wgs_extract_interval_from_plan.side_effect = lambda p: interval(owner, p)
                owner._wgs_uses_fixed_monthly_cutoff.side_effect = lambda p: fixed_monthly(owner, p)
                owner._wgs_get_sale_period_schedule.side_effect = lambda *a, **kw: sale_schedule(owner, *a, **kw)
                owner._wgs_get_subscription_renewal_schedule.side_effect = lambda *a, **kw: schedule(owner, *a, **kw)

                snapshot = build(owner, source, product=product)

                self.assertEqual(snapshot['subscription_start_date'], '2026-11-14')
                self.assertEqual(snapshot['subscription_end_date'], expected_end)
                self.assertEqual(snapshot['plan_id'], 9)
                self.assertEqual(snapshot['display_price_unit'], 799.0)
                owner._wgs_get_subscription_renewal_schedule.assert_called_once_with(
                    source, plan=plan, today=date(2026, 9, 28),
                )
                owner._wgs_get_order_recurrence_delta.assert_not_called()
                source.write.assert_not_called()

    def test_applied_and_legacy_linked_lines_never_reenter_commercial_handlers(self):
        class Lines(list):
            def sorted(self, _key): return self
            def filtered(self, predicate): return Lines(line for line in self if predicate(line))

        sync = method(OPS, '_wgs_sync_subscription_sales')
        for legacy in (False, True):
            order = Mock()
            order.sorted.return_value = [order]
            order.state = 'paid'
            order.partner_id.ids = [7]
            order._wgs_lock_operation_records.return_value._wgs_get_access_related_partner_ids.return_value = set()
            order._wgs_line_operation_input.return_value = {'product': 42, 'price': 100}
            line = Mock()
            line.qty = 1
            line.product_id.recurring_invoice = True
            line.wgs_application_state = False if legacy else 'applied'
            line.wgs_sale_order_id = True
            line.wgs_application_hash = contract.fingerprint({'product': 42, 'price': 100})
            order.lines = Lines([line])
            sync(order)
            sync(order)
            order._wgs_apply_subscription_operation.assert_not_called()
            order._wgs_finalize_paid_access.assert_not_called()
            if not legacy:
                order._wgs_line_operation_input.return_value = {'product': 42, 'price': 90}
                with self.assertRaises(UserError):
                    sync(order)

    def test_browser_numeric_roundtrip_keeps_signature_input(self):
        server = {'pricing': {'price': 100.0, 'discount': 0.0, 'lines': [12.5, -0.0, 1.0]}}
        browser = {'pricing': {'price': 100, 'discount': 0, 'lines': [12.5, 0, 1]}}
        self.assertEqual(contract.canonical_json(server), contract.canonical_json(browser))
        self.assertEqual(contract.fingerprint(server), contract.fingerprint(browser))
        with self.assertRaises(ValueError):
            contract.canonical_json({'price': float('nan')})

    def test_access_period_does_not_recalculate_from_mutable_plan(self):
        get_period = method('witann_group_subscriptions/models/sale_order.py', '_wgs_get_subscription_access_period')
        owner = Mock()
        owner._wgs_get_first_access_date_value.side_effect = [date(2026, 9, 9), date(2026, 10, 8), False]
        owner._wgs_normalize_next_invoice_date_for_access.side_effect = lambda next_date, end: next_date
        result = get_period(owner)
        self.assertEqual(result, dict(start_date=date(2026, 9, 9), valid_until=date(2026, 10, 8), next_invoice_date=date(2026, 10, 9)))
        owner._wgs_get_subscription_recurrence_delta.assert_not_called()

    def test_native_odoo19_existing_draft_is_processed_when_paid(self):
        tree = ast.parse((ROOT / POS).read_text())
        node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_process_order')
        node.decorator_list = []

        class Native:
            def _process_order(self, order, existing_order):
                self.native_existing = existing_order
                order.pop('uuid', None)
                order['lines'] = []
                return 42

        cls = ast.ClassDef(name='Adapter', bases=[ast.Name(id='Native', ctx=ast.Load())], keywords=[], body=[node], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
        namespace = {'Native': Native}
        exec(compile(module, str(POS), 'exec'), namespace)
        for state in ('draft', 'paid'):
            for existing in (False, object()):
                with self.subTest(state=state, existing=bool(existing)):
                    owner = namespace['Adapter']()
                    owner._wgs_disable_invoice_request_for_pos_order_payload = lambda payload: payload
                    owner._wgs_get_order_uuids = lambda payload: [payload['uuid']]
                    owner._wgs_extract_ui_subscription_line_configs = lambda payload: [payload['lines'][0]]
                    owner._wgs_validate_native_order_configuration = Mock()
                    owner._wgs_clear_buffered_subscription_configs = Mock()
                    paid = Mock()
                    owner.browse = Mock(return_value=paid)
                    payload = {'uuid': 'stable-order', 'state': state, 'lines': [{'line_uuid': 'stable-line'}]}
                    self.assertEqual(owner._process_order(payload, existing), 42)
                    self.assertIs(owner.native_existing, existing)
                    if state == 'paid':
                        paid._wgs_apply_subscription_line_configs.assert_called_once_with([{'line_uuid': 'stable-line'}])
                        paid._wgs_sync_subscription_sales.assert_called_once()
                        paid._wgs_align_partner_from_subscription_lines.assert_not_called()
                        paid._wgs_clear_buffered_subscription_configs.assert_called_once_with(['stable-order'])
                    else:
                        owner.browse.assert_not_called()

    def test_metadata_write_targets_only_explicit_subscription(self):
        update = method(POS, '_wgs_sync_subscription_metadata')
        owner, source = Mock(), Mock()
        owner._wgs_to_int = int
        update(owner, source, subscription_end_date=date(2026, 10, 8), recurring_plan_id=8)
        source.write.assert_called_once_with({'end_date': date(2026, 10, 8), 'plan_id': 8})
        owner._wgs_get_subscription_orders_from_base.assert_not_called()

    def test_month_end_calendar(self):
        for start, amount, unit, expected in [
            ('2026-01-31', 1, 'month', '2026-02-27'),
            ('2024-01-31', 1, 'month', '2024-02-28'),
            ('2024-02-29', 1, 'year', '2025-02-27'),
            ('2026-09-09', 1, 'month', '2026-10-08'),
            ('2026-09-09', 15, 'day', '2026-09-23'),
            ('2026-09-09', 1, 'day', '2026-09-09'),
        ]:
            with self.subTest(start=start, unit=unit):
                begin, end, next_date = contract.period(start, amount, unit)
                self.assertEqual(end.isoformat(), expected)
                self.assertEqual(next_date, end + timedelta(days=1))
                contract.validate_period(begin.isoformat(), end.isoformat(), next_date.isoformat())

    def test_all_months_and_terms_are_inclusive(self):
        for year in (2024, 2025, 2026, 2027):
            for month in range(1, 13):
                for day in (1, 15, 28):
                    for amount, unit in ((1, 'day'), (2, 'week'), (1, 'month'), (6, 'month'), (1, 'year')):
                        start, end, boundary = contract.period(date(year, month, day), amount, unit)
                        self.assertLessEqual(start, end)
                        self.assertEqual(end + timedelta(days=1), boundary)

    def test_aligned_period_keeps_actual_start(self):
        self.assertEqual(contract.period('2026-02-15', 12, 'month', aligned=True),
                         (date(2026, 2, 15), date(2026, 2, 28), date(2026, 3, 1)))

    def test_invalid_period_does_not_fallback_to_today(self):
        for args in ((None, 1, 'month'), ('2026-02-01', 0, 'month'), ('2026-02-01', 1, 'unknown')):
            with self.assertRaises((ValueError, TypeError)):
                contract.period(*args)
        with self.assertRaises(ValueError):
            contract.validate_period('2026-02-01', '2026-02-28', '2026-02-28')

    def test_canonical_hash_is_order_independent_but_content_sensitive(self):
        self.assertEqual(contract.fingerprint({'a': 1, 'b': 0}), contract.fingerprint({'b': 0, 'a': 1}))
        self.assertNotEqual(contract.fingerprint({'price': 0}), contract.fingerprint({'price': 100}))
        with self.assertRaises(ValueError):
            contract.fingerprint({'price': float('nan')})

    def test_monthly_normalization_rejects_daily_residue(self):
        owner = Mock()
        owner._wgs_extract_interval_from_plan.return_value = (1, 'month')
        owner._wgs_should_align_plan_to_calendar_month.return_value = False
        owner._wgs_get_plan_period_end_date.return_value = date(2026, 10, 8)
        owner._wgs_get_plan_min_end_threshold.return_value = date(2026, 10, 9)
        result = method(POS, '_wgs_normalize_subscription_period_for_pos')(
            owner, product=object(), plan_record=object(), subscription_start_date='2026-09-09',
            subscription_end_date='2026-09-10', next_billing_date='2026-09-11')
        self.assertEqual(result, (date(2026, 10, 8), date(2026, 10, 9), False))

    def test_closed_subscription_does_not_make_a_paid_renewal_unapplied(self):
        owner, line, source = Mock(), Mock(), Mock()
        source.exists.return_value = source
        line.wgs_subscription_source_id = line.wgs_sale_order_id = source
        line.wgs_subscription_flow = 'reenroll'
        line.wgs_has_subscription_configuration.return_value = True
        owner._wgs_build_paid_subscription_pos_line_issue.return_value = {}
        owner._wgs_is_subscription_order_closed_for_reenroll.return_value = True
        self.assertFalse(method(POS, '_wgs_classify_paid_subscription_pos_line_sync_issue')(owner, line))
        owner._wgs_is_subscription_order_closed_for_reenroll.assert_not_called()

    def test_missing_link_requires_review_not_automatic_repair(self):
        owner, line = Mock(), Mock()
        source = Mock(); source.exists.return_value = source
        line.wgs_subscription_source_id = source
        line.wgs_sale_order_id.exists.return_value = False
        line.wgs_subscription_flow = 'renewal'
        owner._wgs_build_paid_subscription_pos_line_issue.return_value = {}
        result = method(POS, '_wgs_classify_paid_subscription_pos_line_sync_issue')(owner, line)
        self.assertEqual(result['issue'], 'explicit_flow_not_applied')
        self.assertFalse(result['safe_to_repair'])

    def test_every_access_hook_is_deferred_by_central_boundary(self):
        owner = Mock()
        owner._WGS_DEFER_ACCESS_SYNC_CONTEXT_KEY = 'wgs_defer_access_sync'
        owner.env.context = {'wgs_defer_access_sync': True}
        method('witann_group_subscriptions/models/sale_order.py', '_wgs_sync_access_control_people')(owner)
        owner._wgs_get_access_related_partner_ids.assert_not_called()

    def test_quote_signature_and_identity(self):
        sign = method(OPS, '_wgs_quote_signature')
        owner = SimpleNamespace(env={'ir.config_parameter': Mock()})
        owner.env['ir.config_parameter'].sudo.return_value.get_param.return_value = 'test-secret'
        owner._wgs_quote_signature = lambda payload: sign(owner, payload)
        identity = dict(product_id=1, partner_id=2, company_id=9, flow='new', source_id=False)
        payload = dict(product_id=1, partner_id=2, company_id=9, flow='new', source_subscription_id=False,
                       rules_version=1, pricing={'ticket_charge_now': 0})
        snapshot = {'commercial_quote': {'payload': payload, 'signature': sign(owner, payload)}}
        verify = method(OPS, '_wgs_verify_commercial_quote')
        self.assertEqual(verify(owner, snapshot, **identity), payload)
        for key, value in [('product_id', 3), ('company_id', 10), ('partner_id', 5), ('flow', 'renewal')]:
            with self.subTest(key=key), self.assertRaises(UserError):
                verify(owner, snapshot, **{**identity, key: value})
        changed = copy.deepcopy(snapshot)
        changed['commercial_quote']['payload']['pricing']['ticket_charge_now'] = 100
        with self.assertRaises(UserError):
            verify(owner, changed, **identity)

    def test_exact_line_identity_no_first_product_fallback(self):
        class Lines(list):
            def filtered(self, pred): return Lines(value for value in self if pred(value))
        a = SimpleNamespace(uuid='a', product_id=SimpleNamespace(id=1), qty=1)
        b = SimpleNamespace(uuid='b', product_id=SimpleNamespace(id=1), qty=1)
        owner = SimpleNamespace(_wgs_to_int=int, _wgs_to_float=float)
        match = method(POS, '_wgs_match_pos_line_for_ui_config')
        self.assertEqual(match(owner, Lines([a, b]), dict(line_uuid='b', product_id=1, quantity=1)), [b])
        for config in [dict(product_id=1, quantity=1), dict(line_uuid='x', product_id=1, quantity=1),
                       dict(line_uuid='a', product_id=2, quantity=1)]:
            with self.assertRaises(UserError):
                match(owner, Lines([a, b]), config)
        for config in [dict(product_id=1, quantity=1), dict(line_uuid='a', product_id=1, quantity=0)]:
            with self.assertRaises(UserError):
                match(owner, Lines([a]), config)

    def test_partial_refunds_are_rejected_for_qty_price_and_discount(self):
        original = SimpleNamespace(order_id=SimpleNamespace(state='paid', currency_id=SimpleNamespace(
            compare_amounts=lambda a, b: round(a-b, 2))), qty=1, price_unit=100, discount=20)
        owner = Mock()
        validate = method(OPS, '_wgs_validate_full_membership_refund')
        for args in [(-0.5,100,20), (-1,90,20), (-1,100,0)]:
            with self.assertRaises(UserError):
                validate(owner, original, *args)

if __name__ == '__main__':
    unittest.main()
