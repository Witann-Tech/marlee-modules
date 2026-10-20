"""Run checkout eligibility and ownership boundaries without an Odoo server.

These execute production method bodies, but do not replace PostgreSQL/ORM
transaction, concurrency or browser tests against the deployed addon.
"""

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock

from test_subscription_contract import contract, method, OPS, POS, UserError
from test_subscription_application import fixture


class Domain:
    def __init__(self, predicate):
        self.predicate = predicate

    def matches(self, row):
        return self.predicate(row)

    @staticmethod
    def coerce(value):
        if isinstance(value, Domain):
            return value

        def matches(row):
            for name, operator, expected in value:
                actual = row.get(name)
                if operator == '=' and actual != expected:
                    return False
                if operator == '!=' and actual == expected:
                    return False
                if operator == '>' and not actual > expected:
                    return False
                if operator == 'not in' and actual in expected:
                    return False
            return True
        return Domain(matches)

    @staticmethod
    def OR(values):
        domains = [Domain.coerce(value) for value in values]
        return Domain(lambda row: any(domain.matches(row) for domain in domains))

    @staticmethod
    def AND(values):
        domains = [Domain.coerce(value) for value in values]
        return Domain(lambda row: all(domain.matches(row) for domain in domains))


def trial_row(line_id=10, *, order=1, state='paid', claim=False, curp='CURP', trial=True, qty=1):
    return {
        'id': line_id, 'order_id': order, 'order_id.state': state,
        'order_id.partner_id.x_studio_curp': curp, 'wgs_free_trial_curp': claim,
        'product_id.product_tmpl_id.wgs_free_trial_day': trial, 'qty': qty,
    }


def usage_fixture(rows, sale_rows=()):
    sale, pos, owner = Mock(), Mock(), Mock()
    sale.sudo.return_value, pos.sudo.return_value = sale, pos
    sale.search.side_effect = lambda domain, limit: [row for row in sale_rows if Domain.coerce(domain).matches(row)][:limit]
    pos.search.side_effect = lambda domain, limit: [row for row in rows if Domain.coerce(domain).matches(row)][:limit]
    owner.env = MagicMock()
    sale_order = Mock()
    sale_order.sudo.return_value = sale_order
    sale_order._wgs_normalize_partner_curp_for_pos.side_effect = lambda value: value.strip().upper()
    sale_order._wgs_get_partner_curp_field_for_pos.return_value = 'x_studio_curp'
    owner.env.__getitem__.side_effect = {
        'sale.order': sale_order, 'sale.order.line': sale, 'pos.order.line': pos,
    }.__getitem__
    check = method(POS, '_wgs_has_free_trial_usage_for_curp')
    check.__globals__['fields'] = SimpleNamespace(Domain=Domain)
    return owner, check, sale, pos


class Lines(list):
    def sorted(self, key):
        return self

    def filtered(self, predicate):
        return Lines(line for line in self if predicate(line))


class Contracts(list):
    def __sub__(self, other):
        return Contracts(record for record in self if record != other)


class LinkedLines(list):
    def __or__(self, other):
        return LinkedLines([*self, *(record for record in other if record not in self)])

    def exists(self):
        return self

    def filtered(self, predicate):
        return LinkedLines(record for record in self if predicate(record))


def paid_fixture(qty=1):
    owner, line = MagicMock(), Mock()
    owner.sorted.return_value = [owner]
    owner.with_company.return_value = owner
    owner.with_context.return_value = owner
    owner.state = 'paid'
    owner.partner_id.id, owner.partner_id.ids = 7, [7]
    owner._wgs_lock_operation_records.return_value._wgs_get_access_related_partner_ids.return_value = set()
    owner._wgs_line_operation_input.return_value = {'product': 42, 'price': 0}
    owner._wgs_validate_subscription_product_eligibility_for_pos.return_value = {
        'ok': True, 'free_trial_day': True, 'curp': 'CURP',
    }
    line.wgs_subscription_flow = 'new'
    line.qty, line.product_id.recurring_invoice = qty, True
    line.wgs_application_state, line.wgs_sale_order_id = False, False
    line.wgs_pricing_snapshot_json = '{}'
    line.with_env.return_value = line

    def write(values):
        for key, value in values.items():
            setattr(line, key, value)
    line.write.side_effect = write
    owner.lines = Lines([line])
    return owner, line


class TrialEligibilityTests(unittest.TestCase):
    def test_private_paid_eligibility_allows_first_use_not_other_lines(self):
        rows = [trial_row()]
        owner, usage, _sale, _pos = usage_fixture(rows)
        owner.partner_id.id, owner.state = 7, 'paid'
        owner._wgs_get_any_subscription_history_for_partner.return_value = False
        partner = owner._wgs_browse_partner_for_pos.return_value
        product = owner._wgs_browse_product_for_pos.return_value
        product.product_tmpl_id.wgs_free_trial_day = True
        product.product_tmpl_id.wgs_student_age_lock = False
        owner.env['sale.order']._get_partner_curp_for_pos.return_value = 'CURP'
        owner._wgs_has_free_trial_usage_for_curp.side_effect = lambda value, **kw: usage(owner, value, **kw)
        line = Mock(id=10, order_id=owner, qty=1)
        line.product_id.id = 42
        validate = method(POS, '_wgs_validate_subscription_product_eligibility_for_pos')
        self.assertFalse(validate(owner, partner.id, product.id)['ok'])
        owner.partner_id.id = partner.id
        line.product_id.id = product.id
        self.assertTrue(validate(owner, partner.id, product.id, applying_line=line)['ok'])
        rows.append(trial_row(11))
        self.assertEqual(validate(owner, partner.id, product.id, applying_line=line)['error_code'], 'free_trial_already_used')

    def test_first_paid_trial_excludes_only_its_own_line(self):
        owner, check, sale, pos = usage_fixture([trial_row()])
        self.assertTrue(check(owner, ' curp '))
        self.assertFalse(check(owner, ' curp ', excluding_line=SimpleNamespace(id=10)))
        sale.search_count.assert_not_called()
        pos.search_count.assert_not_called()

    def test_another_line_in_same_ticket_is_not_excluded(self):
        owner, check, _sale, _pos = usage_fixture([trial_row(), trial_row(11)])
        self.assertTrue(check(owner, 'CURP', excluding_line=SimpleNamespace(id=10)))

    def test_other_ticket_and_legacy_sale_still_block(self):
        owner, check, _sale, _pos = usage_fixture([trial_row(11, order=2)])
        self.assertTrue(check(owner, 'CURP', excluding_line=SimpleNamespace(id=10)))
        owner, check, _sale, _pos = usage_fixture([], sale_rows=[trial_row()])
        self.assertTrue(check(owner, 'CURP', excluding_line=SimpleNamespace(id=10)))

    def test_captured_curp_survives_refund_customer_and_catalog_changes(self):
        owner, check, _sale, _pos = usage_fixture([
            trial_row(state='cancel', claim='CURP', curp='DIFFERENT', trial=False),
        ])
        self.assertTrue(check(owner, 'CURP'))

    def test_other_curp_unpaid_and_negative_legacy_lines_do_not_consume_trial(self):
        owner, check, _sale, _pos = usage_fixture([
            trial_row(curp='OTHER'), trial_row(11, state='draft'),
            trial_row(12, state='cancel'), trial_row(13, qty=-1),
        ])
        self.assertFalse(check(owner, 'CURP'))

    def test_public_validation_cannot_request_an_exclusion(self):
        owner = Mock()
        validate = method(POS, 'wgs_validate_subscription_product_eligibility_for_pos')
        validate(owner, 7, 42, 'new', False)
        owner._wgs_validate_subscription_product_eligibility_for_pos.assert_called_once_with(7, 42, 'new', False)
        with self.assertRaises(TypeError):
            validate(owner, 7, 42, applying_line=Mock())

    def test_private_exclusion_requires_matching_persisted_paid_line(self):
        validate = method(POS, '_wgs_validate_subscription_product_eligibility_for_pos')
        for mismatch in ('order', 'partner', 'product', 'quantity', 'state'):
            with self.subTest(mismatch=mismatch):
                owner, line = Mock(), Mock()
                owner.partner_id.id, owner.state = 7, 'paid'
                line.order_id, line.product_id.id, line.qty = owner, 42, 1
                if mismatch == 'order':
                    line.order_id = object()
                elif mismatch == 'partner':
                    owner.partner_id.id = 8
                elif mismatch == 'product':
                    line.product_id.id = 43
                elif mismatch == 'quantity':
                    line.qty = -1
                else:
                    owner.state = 'draft'
                with self.assertRaises(UserError):
                    validate(owner, 7, 42, applying_line=line)
                owner._wgs_browse_partner_for_pos.assert_not_called()

    def test_checkout_passes_current_line_claims_before_application_and_replay_skips_it(self):
        owner, line = paid_fixture()
        sync = method(OPS, '_wgs_sync_subscription_sales')
        sync(owner)
        owner._wgs_validate_subscription_product_eligibility_for_pos.assert_called_once_with(
            7, line.product_id.id, 'new', line.wgs_subscription_source_id.id, applying_line=line,
        )
        owner.wgs_validate_subscription_product_eligibility_for_pos.assert_not_called()
        line.flush_recordset.assert_called_once_with(['wgs_free_trial_curp'])
        self.assertEqual(line.wgs_free_trial_curp, 'CURP')
        self.assertEqual(line.wgs_application_state, 'applied')
        self.assertEqual(line.wgs_application_hash, contract.fingerprint({'product': 42, 'price': 0}))
        sync(owner)
        owner._wgs_apply_subscription_operation.assert_called_once_with(line)
        line.flush_recordset.assert_called_once()

    def test_checkout_rejects_multiple_units_before_claim_or_subscription(self):
        owner, line = paid_fixture(qty=2)
        with self.assertRaises(UserError):
            method(OPS, '_wgs_sync_subscription_sales')(owner)
        line.write.assert_not_called()
        owner._wgs_apply_subscription_operation.assert_not_called()

    def test_free_zero_price_nontrial_never_creates_lifetime_claim(self):
        owner, line = paid_fixture()
        owner._wgs_validate_subscription_product_eligibility_for_pos.return_value = {'ok': True, 'free_trial_day': False}
        method(OPS, '_wgs_sync_subscription_sales')(owner)
        line.flush_recordset.assert_not_called()
        self.assertTrue(all('wgs_free_trial_curp' not in call.args[0] for call in line.write.call_args_list))
        owner._wgs_apply_subscription_operation.assert_called_once_with(line)

    def test_preflight_rejects_duplicate_trial_lines_and_quantity_before_payment(self):
        class Products(list):
            @property
            def ids(self):
                return [product.id for product in self]

            def filtered(self, predicate):
                return Products(product for product in self if (
                    getattr(product, predicate) if isinstance(predicate, str) else predicate(product)
                ))

        owner = MagicMock()
        owner.env['product.product'].browse().exists.return_value = Products([
            SimpleNamespace(id=42, recurring_invoice=True, wgs_free_trial_day=True),
        ])
        owner._wgs_to_int.side_effect = lambda value: int(value or 0)
        check = method(OPS, '_wgs_validate_ticket_memberships')
        config = {'line_uuid': 'trial', 'product_id': 42, 'quantity': 1, 'pricing_snapshot': {}}
        first = {'uuid': 'trial', 'product_id': 42, 'qty': 1}
        check(owner, [first], [config])
        with self.assertRaises(UserError):
            check(owner, [{**first, 'qty': 2}], [config])
        with self.assertRaises(UserError):
            check(owner, [first, {**first, 'uuid': 'another-trial'}], [config])


class ParticipantOwnershipTests(unittest.TestCase):
    def test_payment_history_uses_application_target_not_origin_or_stale_native_link(self):
        source, target = SimpleNamespace(id=1), SimpleNamespace(id=2)
        original = SimpleNamespace(wgs_sale_order_id=source, wgs_subscription_source_id=False, sale_order_origin_id=source)
        child = SimpleNamespace(wgs_sale_order_id=target, wgs_subscription_source_id=source, sale_order_origin_id=source)
        legacy = SimpleNamespace(wgs_sale_order_id=False, wgs_subscription_source_id=False, sale_order_origin_id=source)
        records = [original, child, legacy]
        model = Mock()
        model.sudo.return_value = model
        model._fields = {name: SimpleNamespace(type='many2one', comodel_name='sale.order') for name in (
            'wgs_sale_order_id', 'wgs_subscription_source_id', 'sale_order_origin_id',
        )}

        def search(domain):
            name, _operator, value = domain[0]
            return LinkedLines(record for record in records if getattr(getattr(record, name), 'id', False) == value)
        model.search.side_effect = search
        owner = MagicMock()
        owner.env.__getitem__.return_value = model
        source.ensure_one = lambda: None
        result = method(POS, '_wgs_get_pos_lines_linked_to_subscription')(owner, source)
        self.assertEqual(result, [original, legacy])
        self.assertTrue(all(call.args[0][0][0] != 'wgs_subscription_source_id' for call in model.search.call_args_list))

    def test_source_quote_seals_before_checkout_and_validation_checks_buyer(self):
        owner, source, product, buyer = MagicMock(), Mock(), Mock(), Mock()
        owner._wgs_pending_package_changes.return_value = []
        owner._wgs_extract_interval_from_plan.return_value = (1, 'month')
        pricing = {
            'plan_id': 3, 'subscription_start_date': '2026-10-20',
            'subscription_end_date': '2026-11-20', 'next_billing_date': '2026-11-21',
        }
        seal = method(OPS, '_wgs_seal_pricing_payload')
        seal.__globals__['validate_period'] = contract.validate_period
        for flow in ('renewal', 'reenroll', 'upsale'):
            result = seal(owner, pricing, {'source_order': source, 'product': product, 'partner': buyer, 'flow': flow})
            self.assertEqual(result['commercial_quote']['payload']['flow'], flow)
        source_model, partner_model = Mock(), Mock()
        source_model.browse.return_value.exists.return_value = source
        partner_model.browse.return_value.exists.return_value = buyer
        owner.env.__getitem__.side_effect = {'sale.order': source_model, 'res.partner': partner_model}.__getitem__
        owner._wgs_source_revision.return_value = 'original'
        result = method(OPS, '_wgs_validate_operation_source')(owner, {
            'source_subscription_id': source.id, 'source_revision': 'original',
            'flow': 'reenroll', 'partner_id': buyer.id,
        })
        self.assertIs(result, source)
        owner._wgs_reenrollment_requires_new_contract.assert_called_once_with(source, buyer)

    def test_owner_reuses_contract_participant_branches_and_stranger_is_rejected(self):
        owner, member, stranger = Mock(), Mock(), Mock()
        source = Mock(partner_id=owner, participant_ids=[owner, member])
        service = Mock()
        service._wgs_find_subscription_history_for_partner.return_value = Contracts([source])
        policy = method(POS, '_wgs_reenrollment_requires_new_contract')
        self.assertFalse(policy(service, source, owner))
        self.assertTrue(policy(service, source, member))
        with self.assertRaises(UserError):
            policy(service, source, stranger)

    def test_original_contract_cannot_sell_another_independent_membership(self):
        buyer = Mock()
        source = Mock(partner_id=Mock(), participant_ids=[buyer])
        service, other = Mock(), Mock()
        service._wgs_find_subscription_history_for_partner.return_value = Contracts([source, other])
        check = method(POS, '_wgs_reenrollment_requires_new_contract')
        for state in ({'can_renew': True, 'state_key': 'progress'}, {'can_renew': False, 'state_key': 'future'}):
            with self.subTest(state=state):
                other._wgs_subscription_operation_policy_for_pos.return_value = state
                with self.assertRaises(UserError):
                    check(service, source, buyer)
        other._wgs_subscription_operation_policy_for_pos.return_value = {'can_renew': False, 'state_key': 'closed'}
        self.assertTrue(check(service, source, buyer))

    def test_participant_handler_delegates_native_creation_without_reassigning_source(self):
        owner, line, source = Mock(), Mock(), Mock()
        line.qty = 1
        line.wgs_subscription_source_id = source
        source.exists.return_value = source
        owner._wgs_reenrollment_requires_new_contract.return_value = True
        result = method(POS, '_wgs_process_subscription_reenroll_line')(owner, line)
        self.assertIs(result, owner._wgs_create_subscription_sale_order_from_line.return_value)
        owner._wgs_create_subscription_sale_order_from_line.assert_called_once_with(line)
        source.write.assert_not_called()
        owner._wgs_reactivate_subscription_order_for_pos.assert_not_called()
        owner._wgs_apply_domiciliation_contract_from_pos_line.assert_not_called()

    def test_postcondition_checks_original_identity_even_if_handler_reassigns_it(self):
        owner, line, target, pricing = fixture()
        source = SimpleNamespace(partner_id=object())
        target.wgs_reenrollment_source_id = source
        owner._wgs_assert_subscription_application(line, target, pricing, before='unchanged', preserved_source=source)
        # A reassignment must not disable the guard by changing its condition.
        source.partner_id = owner.partner_id
        owner._wgs_source_revision = lambda record: 'changed'
        with self.assertRaises(UserError):
            owner._wgs_assert_subscription_application(line, target, pricing, before='unchanged', preserved_source=source)

    def test_postcondition_rejects_source_reuse_or_missing_lineage(self):
        owner, line, target, pricing = fixture()
        target.wgs_reenrollment_source_id = object()
        with self.assertRaises(UserError):
            owner._wgs_assert_subscription_application(line, target, pricing, before='unchanged', preserved_source=target)
        source = object()
        with self.assertRaises(UserError):
            owner._wgs_assert_subscription_application(line, target, pricing, before='unchanged', preserved_source=source)


if __name__ == '__main__':
    unittest.main()
