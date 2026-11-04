"""Commercial integration gate. Run on a disposable Odoo 19 Enterprise database."""

import json
from copy import deepcopy
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from psycopg2 import IntegrityError
from psycopg2.errors import SerializationFailure

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import CommonPosTest

from .common import create_recurring_price, create_tax
from odoo.addons.witann_group_subscriptions.models.subscription_lifecycle import SaleOrderWgsLifecycle
from odoo.addons.witann_group_subscriptions.tests.common import ensure_partner_identity_fields


@tagged('post_install', '-at_install', 'wgs_commercial')
class TestSubscriptionOperations(CommonPosTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ensure_partner_identity_fields(cls.env)

    def create_backend_pos_order(self, data):
        # Core's helper copies every tax of a shared product, including other
        # companies. The real POS loads only taxes of the selected company.
        lines = []
        for values in data.get('line_data', []):
            taxes = self.env['product.product'].sudo().browse(values['product_id']).taxes_id.filtered_domain([
                ('company_id', '=', self.env.company.id),
            ])
            lines.append({'tax_ids': [Command.set(taxes.ids)], **values})
        return super().create_backend_pos_order({**data, 'line_data': lines})

    def setUp(self):
        super().setUp()
        self.Pos = self.env['pos.order']
        self.clock = patch.object(fields.Datetime, 'now', return_value=datetime(2026, 9, 15, 12))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.holder = self.env['res.partner'].create({'name': 'Commercial flow holder'})
        self.member = self.env['res.partner'].create({'name': 'Commercial flow participant'})
        self.site = self.env['access_control.site'].sudo().create({
            'name': 'Commercial QA site', 'code': str(uuid4()), 'company_id': self.env.company.id,
        })
        self.month = self.env['sale.subscription.plan'].sudo().create({
            'name': 'Monthly contract test', 'billing_period_value': 1, 'billing_period_unit': 'month',
        })
        self.day = self.env['sale.subscription.plan'].sudo().create({
            'name': 'Daily contract test', 'billing_period_value': 1, 'billing_period_unit': 'week',
            'wgs_single_day_plan': True,
        })
        self.solo = self._product('Solo', self.month, 100)
        self.pair = self._product('Pair', self.month, 180, capacity=2)
        self.daily = self._product('Daily', self.day, 10)
        self.daily.wgs_single_day_access = True

    def _product(self, name, plan, amount, capacity=1):
        product = self.env['product.product'].create({
            'name': name, 'type': 'service', 'recurring_invoice': True,
            'company_id': self.env.company.id,
            'available_in_pos': True, 'list_price': amount, 'taxes_id': [Command.clear()],
            'max_participants_total': capacity,
            'wgs_access_site_ids': [Command.set(self.site.ids)],
        })
        create_recurring_price(self.env, product, plan, amount)
        return product

    def _quote(self, product, plan, flow='new', source=False, start='2026-09-15', months=False):
        return self.Pos.wgs_get_subscription_pricing_for_pos(
            partner_id=self.holder.id, product_id=product.id, flow=flow,
            source_subscription_id=source.id if source else False,
            preferred_plan_id=plan.id if plan else False, start_date=start,
            domiciliation_installment_sequences=months,
        )

    def _paid(self, product, plan, flow='new', source=False, participants=False, start='2026-09-15', months=False, discount=0, submit=False):
        quote = self._quote(product, plan, flow, source, start, months)
        config = {
            'line_uuid': str(uuid4()), 'product_id': product.id, 'quantity': 1,
            'flow': flow, 'partner_id': self.holder.id,
            'source_subscription_id': source.id if source else False,
            'plan_id': quote['plan_id'], 'pricing_id': quote.get('pricing_id'),
            'participant_ids': participants or self.holder.ids,
            'pricing_snapshot': quote, 'pricing_lock': {'price_unit': quote['ticket_charge_now'], 'discount': 0},
        }
        if discount:
            employee = self.env['hr.employee'].sudo().create({'name': 'WGS test supervisor'})
            pin = str(uuid4())
            self.env['wgs.pos.authorization.credential'].sudo().create({
                'employee_id': employee.id, 'authorization_pin': pin,
            })
            authorization = self.Pos.wgs_authorize_subscription_discount_for_pos(
                self.holder.id, product.id, flow, discount, pin, source.id if source else False,
            )
            self.assertTrue(authorization['ok'])
            config.update({
                'discount_percent': discount, 'discount_code': authorization['code'],
                'discount_authorized_employee_id': employee.id,
                'discount_authorized_at': authorization['authorized_at'],
            })
        order, _refund = self.create_backend_pos_order({
            'order_data': {'partner_id': self.holder.id},
            'line_data': [{
                'uuid': config['line_uuid'], 'product_id': product.id, 'qty': 1,
                'price_unit': quote['ticket_charge_now'], 'wgs_operation_config_json': json.dumps(config),
            }],
        })
        self.Pos.wgs_stage_subscription_config_for_uuid(order.uuid, [config], {
            'partner_id': self.holder.id, 'company_id': order.company_id.id,
            'lines': [{'uuid': config['line_uuid'], 'product_id': product.id, 'qty': 1,
                       'price_unit': quote['ticket_charge_now'], 'discount': discount}],
        })
        totals = product.taxes_id.compute_all(
            quote['ticket_charge_now'] * (1 - discount / 100), currency=order.currency_id,
            quantity=1, product=product, partner=self.holder,
        )
        amount, subtotal = totals['total_included'], totals['total_excluded']
        payload = {
            'uuid': order.uuid, 'state': 'paid', 'session_id': order.session_id.id,
            'partner_id': self.holder.id, 'amount_return': 0,
            'amount_total': amount, 'amount_paid': amount, 'amount_tax': amount - subtotal,
            'to_invoice': False, 'wgs_subscription_configs': [config],
            'lines': [[1, order.lines.id, {
                'uuid': config['line_uuid'], 'product_id': product.id, 'qty': 1,
                'price_unit': quote['ticket_charge_now'], 'discount': discount,
                'price_subtotal': subtotal, 'price_subtotal_incl': amount,
            }]],
            'payment_ids': [[0, 0, {
                'payment_method_id': self.cash_payment_method.id,
                'amount': amount, 'payment_date': fields.Datetime.now(),
            }]] if amount else [],
        }
        if submit:
            submit(order, payload)
        else:
            self.Pos._process_order(payload, order)
        self.assertEqual(order.state, 'paid')
        self.assertEqual(sum(order.payment_ids.mapped('amount')), amount)
        # Inspect backend state as an administrator; the checkout above runs
        # with the POS user's real ACLs, without granting that user Sales rights.
        return order, order.lines.wgs_sale_order_id.sudo()

    def test_paid_new_has_one_application_and_exact_month(self):
        order, subscription = self._paid(self.solo, self.month)
        self.assertEqual(subscription.plan_id, self.month)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-15'))
        self.assertEqual(subscription.wgs_monthly_cutoff_day, 15)
        self.assertEqual(subscription.next_invoice_date, fields.Date.to_date('2026-10-16'))
        self.assertEqual(order.lines.wgs_application_state, 'applied')
        receipt = order.lines.wgs_application_receipt
        order._wgs_sync_subscription_sales()
        self.assertEqual(order.lines.wgs_application_receipt, receipt)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-15'))

    def test_replay_after_closure_does_not_reactivate_or_extend(self):
        order, subscription = self._paid(self.solo, self.month)
        subscription.write({'subscription_state': '6_churn'})
        order._wgs_sync_subscription_sales()
        self.assertEqual(subscription.subscription_state, '6_churn')
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-15'))

    def test_pos_cashier_applies_membership_without_backend_sales_create_access(self):
        self.assertFalse(self.env.su)
        with self.assertRaises(AccessError):
            self.env['sale.order'].check_access('create')
        order, subscription = self._paid(self.solo, self.month)
        self.assertEqual(subscription.subscription_state, '3_progress')
        self.assertEqual(order.lines.wgs_application_state, 'applied')

    def test_catalog_price_and_new_plan_are_not_stale_in_the_same_environment(self):
        first = self._quote(self.solo, self.month)
        price = self.env['product.pricelist.item'].sudo().search([
            ('product_tmpl_id', '=', self.solo.product_tmpl_id.id), ('plan_id', '=', self.month.id),
        ])
        price.fixed_price = 125
        self.assertEqual(self._quote(self.solo, self.month)['recurring_price'], 125)
        self.assertEqual(first['recurring_price'], 100)
        annual = self.env['sale.subscription.plan'].sudo().create({
            'name': 'New catalog annual', 'billing_period_value': 1, 'billing_period_unit': 'year',
        })
        create_recurring_price(self.env, self.solo, annual, 1000)
        quote = self._quote(self.solo, annual)
        self.assertEqual(quote['plan_id'], annual.id)
        self.assertEqual(quote['recurring_price'], 1000)
        self.assertEqual(quote['subscription_end_date'], '2027-09-14')

    def test_removed_catalog_tariff_cannot_survive_a_custom_environment_cache(self):
        self._quote(self.solo, self.month)
        self.env['product.pricelist.item'].sudo().search([
            ('product_tmpl_id', '=', self.solo.product_tmpl_id.id), ('plan_id', '=', self.month.id),
        ]).unlink()
        with self.assertRaises(UserError):
            self._quote(self.solo, self.month)

    def test_application_does_not_elevate_a_non_pos_user(self):
        order, _subscription = self._paid(self.solo, self.month)
        user = self.env['res.users'].sudo().create({
            'name': 'Non POS application test', 'login': str(uuid4()),
            'group_ids': [Command.set(self.env.ref('base.group_user').ids)],
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
        })
        with self.assertRaises(UserError):
            order.with_user(user)._wgs_sync_subscription_sales()

    def test_application_keeps_the_pos_company_record_rule_before_elevation(self):
        order, _subscription = self._paid(self.solo, self.month)
        other = self.env['res.company'].sudo().create({'name': 'Other company application test'})
        user = self.env['res.users'].sudo().create({
            'name': 'Other company POS user', 'login': str(uuid4()),
            'group_ids': [Command.set((self.env.ref('base.group_user') | self.env.ref('point_of_sale.group_pos_user')).ids)],
            'company_id': other.id, 'company_ids': [Command.set(other.ids)],
        })
        with self.assertRaises(AccessError):
            order.with_user(user).with_context(allowed_company_ids=other.ids)._wgs_sync_subscription_sales()

    def test_holder_is_not_inferred_from_participant_order(self):
        self.holder, self.member = self.member, self.holder
        self.assertLess(self.member.id, self.holder.id)
        order, subscription = self._paid(
            self.pair, self.month, participants=[self.member.id, self.holder.id],
        )
        self.assertEqual(order.partner_id, self.holder)
        self.assertEqual(subscription.partner_id, self.holder)
        self.assertEqual(set(subscription.participant_ids.ids), set((self.holder | self.member).ids))

    def test_first_free_trial_applies_once_and_replay_keeps_its_claim(self):
        curp_field = self.env['sale.order']._wgs_get_partner_curp_field_for_pos()
        if not curp_field:
            self.skipTest('The production CURP field is not installed in this test database.')
        self.holder.write({curp_field: 'QATR010101HASBRS01'})
        trial = self._product('First free trial', self.day, 0)
        trial.wgs_free_trial_day = True
        order, subscription = self._paid(trial, self.day)
        self.assertEqual(order.lines.wgs_application_state, 'applied')
        self.assertEqual(order.lines.wgs_free_trial_curp, 'QATR010101HASBRS01')
        self.assertEqual(subscription.start_date, subscription.end_date)
        self.assertEqual(subscription.partner_id, self.holder)
        receipt = order.lines.wgs_application_receipt
        order._wgs_sync_subscription_sales()
        self.assertEqual(order.lines.wgs_application_receipt, receipt)
        self.assertEqual(order.lines.wgs_free_trial_curp, 'QATR010101HASBRS01')
        self.assertFalse(self.Pos.wgs_validate_subscription_product_eligibility_for_pos(
            self.holder.id, trial.id,
        )['ok'])
        # Neither a refund nor customer/catalog edits erase the captured use.
        refund, _unused = self.create_backend_pos_order({
            'order_data': {'partner_id': self.holder.id, 'state': 'paid'},
            'line_data': [{
                'product_id': trial.id, 'qty': -1, 'price_unit': 0,
                'refunded_orderline_id': order.lines.id,
            }],
        })
        refund._wgs_sync_subscription_sales()
        self.holder.write({curp_field: 'QATR020202HASBRS02'})
        trial.wgs_free_trial_day = False
        self.assertTrue(self.Pos._wgs_has_free_trial_usage_for_curp('QATR010101HASBRS01'))

    def test_trial_claim_is_unique_across_distinct_customers_and_rolls_back(self):
        first, _unused = self.create_backend_pos_order({
            'order_data': {'partner_id': self.holder.id},
            'line_data': [{'product_id': self.daily.id, 'qty': 1, 'price_unit': 0}],
        })
        second, _unused = self.create_backend_pos_order({
            'order_data': {'partner_id': self.member.id},
            'line_data': [{'product_id': self.daily.id, 'qty': 1, 'price_unit': 0}],
        })
        first.lines.write({'wgs_free_trial_curp': 'QATR010101HASBRS01'})
        first.lines.flush_recordset(['wgs_free_trial_curp'])
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            second.lines.write({'wgs_free_trial_curp': 'QATR010101HASBRS01'})
            second.lines.flush_recordset(['wgs_free_trial_curp'])
        self.assertFalse(second.lines.wgs_free_trial_curp)
        with self.assertRaisesRegex(UserError, 'abort claim'), self.env.cr.savepoint():
            second.lines.write({'wgs_free_trial_curp': 'QATR020202HASBRS02'})
            second.lines.flush_recordset(['wgs_free_trial_curp'])
            raise UserError('abort claim')
        self.assertFalse(second.lines.wgs_free_trial_curp)
        self.assertFalse(self.Pos._wgs_has_free_trial_usage_for_curp('QATR020202HASBRS02'))

    def test_participant_reenrollment_preserves_source_history_and_refund_isolation(self):
        original, source = self._paid(self.pair, self.month, participants=(self.holder | self.member).ids)
        source.subscription_state = '6_churn'
        old_holder = self.holder
        before = self.Pos._wgs_source_revision(source)
        payment_fields = ['amount', 'pos_order_id', 'payment_method_id']
        old_payments = original.payment_ids.read(payment_fields)
        self.holder = self.member
        payment, target = self._paid(self.solo, self.month, 'reenroll', source)
        self.assertNotEqual(target, source)
        self.assertEqual(target.partner_id, self.member)
        self.assertEqual(target.participant_ids, self.member)
        self.assertEqual(target.wgs_reenrollment_source_id, source)
        self.assertEqual(payment.lines.wgs_subscription_source_id, source)
        self.assertEqual(source.partner_id, old_holder)
        self.assertEqual(self.Pos._wgs_source_revision(source), before)
        self.assertEqual(original.payment_ids.read(payment_fields), old_payments)
        self.assertEqual(original.lines.wgs_sale_order_id, source)
        self.assertNotIn(payment.lines, payment._wgs_get_pos_lines_linked_to_subscription(source))
        self.assertTrue(self.env['sale.order']._wgs_partner_has_subscription_history_for_pos(old_holder))
        self.assertTrue(self.Pos._wgs_get_any_subscription_history_for_partner(old_holder))
        receipt = payment.lines.wgs_application_receipt
        payment._wgs_sync_subscription_sales()
        self.assertEqual(payment.lines.wgs_application_receipt, receipt)
        self.assertEqual(self.Pos._wgs_source_revision(source), before)
        with self.assertRaisesRegex(UserError, 'otra membresia vigente o programada'):
            self._quote(self.solo, self.month, 'reenroll', source)
        _renewal, result = self._paid(self.solo, self.month, 'renewal', target)
        self.assertEqual(result, target)
        self.assertEqual(self.Pos._wgs_source_revision(source), before)
        refund, _unused = self.create_backend_pos_order({
            'order_data': {'partner_id': self.member.id, 'state': 'paid'},
            'line_data': [{
                'product_id': self.solo.id, 'qty': -1, 'price_unit': payment.lines.price_unit,
                'refunded_orderline_id': payment.lines.id,
            }],
        })
        refund._wgs_sync_subscription_sales()
        self.assertEqual(refund.lines.wgs_sale_order_id, target)
        self.assertTrue(payment._wgs_is_subscription_order_closed_for_reenroll(target))
        self.assertEqual(self.Pos._wgs_source_revision(source), before)

    def test_participant_reenrollment_to_domiciliation_creates_own_installments(self):
        _original, source = self._paid(self.pair, self.month, participants=(self.holder | self.member).ids)
        source.subscription_state = '6_churn'
        before = self.Pos._wgs_source_revision(source)
        self.month.wgs_domiciliation_enabled = True
        self.holder = self.member
        _payment, target = self._paid(self.solo, self.month, 'reenroll', source, months=[1, 12])
        self.assertNotEqual(target, source)
        self.assertEqual(target.wgs_domiciliation_contract_id.partner_id, self.member)
        self.assertEqual(target.wgs_domiciliation_contract_id.subscription_id, target)
        self.assertFalse(source.wgs_domiciliation_contract_id)
        self.assertEqual(self.Pos._wgs_source_revision(source), before)

    def test_unrelated_buyer_cannot_reenroll_from_someone_elses_contract(self):
        _original, source = self._paid(self.solo, self.month)
        source.subscription_state = '6_churn'
        self.holder = self.member
        with self.assertRaisesRegex(UserError, 'titular ni participante'):
            self._quote(self.solo, self.month, 'reenroll', source)

    def test_refunded_contract_stays_visible_and_reenrollment_preserves_cancelled_history(self):
        payment, source = self._paid(self.solo, self.month)
        before_payments = payment.payment_ids.read(['amount', 'pos_order_id', 'payment_method_id'])
        refund, _unused = self.create_backend_pos_order({
            'order_data': {'partner_id': self.holder.id, 'state': 'paid'},
            'line_data': [{
                'product_id': self.solo.id, 'qty': -1, 'price_unit': payment.lines.price_unit,
                'refunded_orderline_id': payment.lines.id,
            }],
        })
        refund._wgs_sync_subscription_sales()
        self.assertEqual(source.state, 'cancel')
        self.assertTrue(source._is_subscription_record_for_pos())
        Sale = self.env['sale.order']
        company = source.company_id
        self.assertIn(source, Sale._get_pos_subscription_orders(self.holder, company=company))
        self.assertIn(source, Sale._get_pos_subscription_orders_by_partners(self.holder, company=company)[self.holder.id])
        self.assertTrue(Sale._wgs_partner_has_subscription_history_for_pos(self.holder, company=company))
        self.assertIn(source, self.Pos._wgs_find_subscription_history_for_partner(self.holder, company=company))
        status = source._build_pos_subscription_status_item(fields.Date.today())
        self.assertEqual(status['native_state_key'], 'cancel')
        self.assertTrue(status['can_reenroll'])
        self.assertFalse(status['can_renew'])
        self.assertFalse(status['is_valid'])
        with self.assertRaises(UserError):
            self._quote(self.solo, self.month)
        before = self.Pos._wgs_source_revision(source)
        new_payment, target = self._paid(self.solo, self.month, 'reenroll', source)
        self.assertNotEqual(target, source)
        self.assertEqual(target.state, 'sale')
        self.assertEqual(target.wgs_reenrollment_source_id, source)
        self.assertEqual(new_payment.lines.wgs_subscription_source_id, source)
        self.assertEqual(self.Pos._wgs_source_revision(source), before)
        self.assertEqual(payment.payment_ids.read(['amount', 'pos_order_id', 'payment_method_id']), before_payments)
        self.assertNotIn(new_payment.lines, new_payment._wgs_get_pos_lines_linked_to_subscription(source))
        with self.assertRaises(UserError):
            self._quote(self.solo, self.month, 'reenroll', source)

    def test_cancelled_unpaid_recurring_quote_is_not_membership_history(self):
        quote = self.env['sale.order'].sudo().create({
            'partner_id': self.holder.id, 'plan_id': self.month.id,
            'order_line': [Command.create({'product_id': self.solo.id, 'product_uom_qty': 1, 'price_unit': 100})],
        })
        quote.action_cancel()
        self.assertFalse(quote._is_subscription_record_for_pos())
        self.assertFalse(self.env['sale.order']._wgs_partner_has_subscription_history_for_pos(self.holder))
        self.assertFalse(self.Pos._wgs_find_subscription_history_for_partner(self.holder))

    def test_payment_preflight_accepts_identical_retry_after_lost_response(self):
        order, subscription = self._paid(self.solo, self.month)
        config = json.loads(order.lines.wgs_operation_config_json)
        result = self.Pos.wgs_stage_subscription_config_for_uuid(order.uuid, [config], {
            'partner_id': self.holder.id, 'company_id': order.company_id.id,
        })
        self.assertTrue(result['already_applied'])
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-15'))
        config['discount_percent'] = 10
        with self.assertRaises(UserError):
            self.Pos.wgs_stage_subscription_config_for_uuid(order.uuid, [config], {
                'partner_id': self.holder.id, 'company_id': order.company_id.id,
            })

    def test_native_sync_retry_does_not_consume_rpc_arguments_or_duplicate_payment(self):
        def retry_checkout(order, payload):
            arguments = [payload]
            original = deepcopy(arguments)
            Order = type(order)
            saved = Order._process_saved_order
            fail_once = True

            def fail_after_native_payload_consumption(records, draft):
                nonlocal fail_once
                if fail_once:
                    fail_once = False
                    raise SerializationFailure('test native transaction retry')
                return saved(records, draft)

            with patch.object(Order, '_process_saved_order', fail_after_native_payload_consumption):
                with self.assertRaises(SerializationFailure), self.env.cr.savepoint():
                    self.Pos.sync_from_ui(arguments)
                self.assertEqual(arguments, original)
                self.Pos.sync_from_ui(arguments)
            self.assertEqual(arguments, original)
            end = order.lines.wgs_sale_order_id.sudo().end_date
            self.Pos.sync_from_ui(arguments)
            self.assertEqual(arguments, original)
            self.assertEqual(order.lines.wgs_sale_order_id.sudo().end_date, end)
            self.assertEqual(len(order.payment_ids), 1)
            self.assertEqual(len(order.lines), 1)

        order, subscription = self._paid(self.solo, self.month, submit=retry_checkout)
        self.assertEqual(order.lines.wgs_application_state, 'applied')
        self.assertEqual(subscription.plan_id, self.month)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-15'))

    def test_daily_to_monthly_reenrollment_replaces_plan_and_period(self):
        _order, subscription = self._paid(self.daily, self.day)
        subscription.write({'subscription_state': '6_churn'})
        order, result = self._paid(self.solo, self.month, 'reenroll', subscription)
        self.assertEqual(result, subscription)
        self.assertEqual(result.plan_id, self.month)
        self.assertEqual(result.wgs_monthly_cutoff_day, 15)
        self.assertEqual(result.end_date, fields.Date.to_date('2026-10-15'))
        self.assertEqual(result._get_recurring_lines().product_id, self.solo)
        order._wgs_sync_subscription_sales()
        self.assertEqual(result.end_date, fields.Date.to_date('2026-10-15'))

    def test_daily_has_no_invoice_date_and_replays_without_extending(self):
        order, subscription = self._paid(self.daily, self.day)
        self.assertFalse(subscription.next_invoice_date)
        self.assertEqual(subscription.start_date, subscription.end_date)
        receipt = order.lines.wgs_application_receipt
        order._wgs_sync_subscription_sales()
        self.assertEqual(order.lines.wgs_application_receipt, receipt)
        self.assertFalse(subscription.next_invoice_date)

    def test_expired_before_cron_is_reenrollable_in_both_ui_and_checkout(self):
        self.month.auto_close_limit = 3
        _order, subscription = self._paid(self.solo, self.month)
        self.assertEqual(subscription.subscription_state, '3_progress')
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 11, 15, 12)):
            item = subscription._build_pos_subscription_status_item(fields.Date.to_date('2026-11-15'))
            self.assertTrue(item['can_reenroll'])
            self.assertFalse(item['can_renew'])
            _payment, result = self._paid(self.solo, self.month, 'reenroll', subscription, start='2026-11-15')
        self.assertEqual(result.end_date, fields.Date.to_date('2026-12-15'))
        self.assertEqual(result.subscription_state, '3_progress')

    def test_same_day_upsale_closes_source_without_inverting_its_period(self):
        _order, source = self._paid(self.solo, self.month)
        old_period = source._wgs_get_subscription_access_period()
        payment, target = self._paid(self.pair, self.month, 'upsale', source,
                                     participants=(self.holder | self.member).ids)
        self.assertNotEqual(source, target)
        self.assertEqual(source._wgs_get_subscription_access_period(), old_period)
        self.assertIn(source._wgs_get_subscription_state_category(), ('closed', 'cancel'))
        self.assertEqual(payment.lines.wgs_application_state, 'applied')
        self.assertFalse(source._classify_subscription_access_state_for_pos())

    def test_paid_activation_delayed_beyond_grace_applies_original_period(self):
        self.month.auto_close_limit = 3
        _initial, subscription = self._paid(self.solo, self.month)
        payment, _source = self._paid(self.pair, self.month, 'renewal', subscription,
                                     participants=(self.holder | self.member).ids)
        self.assertEqual(payment.lines.wgs_application_state, 'scheduled')
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 12, 15, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(payment.lines.wgs_application_state, 'applied')
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-11-15'))
        self.assertEqual(subscription.plan_id, self.month)

    def test_manual_native_close_cancels_domiciliation_but_keeps_payments(self):
        self.month.wgs_domiciliation_enabled = True
        _payment, subscription = self._paid(self.solo, self.month, months=[1, 12])
        contract = subscription.wgs_domiciliation_contract_id
        old_ids = contract.installment_ids.ids
        paid_ids = contract.installment_ids.filtered(lambda item: item.state == 'paid').ids
        subscription.set_close()
        self.assertEqual(contract.state, 'cancelled')
        self.assertEqual(contract.installment_ids.ids, old_ids)
        self.assertEqual(contract.installment_ids.filtered(lambda item: item.state == 'paid').ids, paid_ids)
        self.assertFalse(subscription._classify_subscription_access_state_for_pos())
        self.assertTrue(subscription._wgs_subscription_operation_policy_for_pos()['can_reenroll'])

    def test_reenrollment_applies_each_purchased_term_not_the_old_plan(self):
        for months, expected_end in ((3, '2026-12-14'), (6, '2027-03-14'), (12, '2027-09-14')):
            with self.subTest(months=months):
                self.holder = self.env['res.partner'].create({'name': f'Reenrollment {months}'})
                target_plan = self.env['sale.subscription.plan'].sudo().create({
                    'name': f'{months} months', 'billing_period_value': months, 'billing_period_unit': 'month',
                })
                target = self._product(f'Package {months}', target_plan, 100 * months)
                _initial, subscription = self._paid(self.solo, self.month)
                subscription.subscription_state = '6_churn'
                _payment, subscription = self._paid(target, target_plan, 'reenroll', subscription)
                self.assertEqual(subscription.plan_id, target_plan)
                self.assertEqual(subscription.order_line.filtered(lambda item: item.product_uom_qty > 0).subscription_plan_id, target_plan)
                self.assertEqual(subscription.end_date, fields.Date.to_date(expected_end))
                self.assertEqual(subscription.wgs_monthly_cutoff_day, 0)

    def test_signed_quote_owns_plan_even_if_redundant_line_metadata_drifts(self):
        quote = self._quote(self.solo, self.month)
        line = self.env['pos.order.line'].new({
            'product_id': self.solo.id, 'qty': 1, 'price_unit': 100,
            'wgs_subscription_flow': 'new', 'wgs_subscription_plan_id': self.day.id,
            'wgs_pricing_snapshot_json': json.dumps(quote),
        })
        order = self.Pos.new({'partner_id': self.holder.id, 'company_id': self.env.company.id})
        pricing = order._wgs_get_persisted_subscription_pricing_from_pos_line(line)
        self.assertEqual(pricing['plan_id'], self.month.id)
        self.assertEqual(pricing['subscription_end_date'], fields.Date.to_date('2026-10-15'))

    def test_native_line_values_never_write_the_related_subscription_plan(self):
        order, subscription = self._paid(self.solo, self.month)
        values = order._wgs_build_subscription_recurring_line_values_for_pos(
            pos_line=order.lines,
            product=self.daily, qty=1, recurring_price_unit=10,
        )
        self.assertNotIn('subscription_plan_id', values)
        self.assertNotIn('subscription_pricing_id', values)

    def test_incorrect_reenrollment_result_rolls_back_without_application_receipt(self):
        _initial, subscription = self._paid(self.daily, self.day)
        subscription.subscription_state = '6_churn'
        original = type(self.Pos)._wgs_sync_subscription_metadata

        def omit_plan(records, **values):
            values.pop('recurring_plan_id', None)
            return original(records, **values)

        with patch.object(type(self.Pos), '_wgs_sync_subscription_metadata', omit_plan):
            with self.assertRaises(UserError), self.env.cr.savepoint():
                self._paid(self.solo, self.month, 'reenroll', subscription)
        self.assertEqual(subscription.plan_id, self.day)
        self.assertEqual(subscription.subscription_state, '6_churn')
        self.assertEqual(subscription.order_line.filtered(lambda item: item.product_uom_qty > 0).product_id, self.daily)

    def test_incorrect_activation_rolls_back_and_retries_without_quarantine(self):
        _initial, subscription = self._paid(self.solo, self.month)
        annual = self.env['sale.subscription.plan'].sudo().create({
            'name': 'Annual future result', 'billing_period_value': 12, 'billing_period_unit': 'month',
        })
        target = self._product('Annual future package', annual, 1200)
        payment, _subscription = self._paid(target, annual, 'renewal', subscription)
        receipt = payment.lines.wgs_application_receipt
        original = type(self.Pos)._wgs_sync_subscription_metadata

        def omit_plan(records, **values):
            values.pop('recurring_plan_id', None)
            return original(records, **values)

        with patch.object(type(self.Pos), '_wgs_sync_subscription_metadata', omit_plan), patch.object(
            fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12),
        ):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(payment.lines.wgs_application_state, 'scheduled')
        self.assertTrue(payment.lines.wgs_activation_error)
        self.assertEqual(payment.lines.wgs_activation_attempts, 1)
        self.assertEqual(payment.lines.wgs_application_receipt, receipt)
        self.assertEqual(subscription.plan_id, self.month)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-15'))
        self.assertEqual(subscription._get_recurring_lines().product_id, self.solo)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 13)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(payment.lines.wgs_application_state, 'applied')
        self.assertFalse(payment.lines.wgs_activation_error)
        self.assertFalse(payment.lines.wgs_activation_retry_at)
        self.assertEqual(subscription.plan_id, annual)

    def test_failed_legacy_queue_does_not_starve_other_due_contracts(self):
        _initial, blocked = self._paid(self.solo, self.month)
        review, _subscription = self._paid(self.pair, self.month, 'renewal', blocked, (self.holder | self.member).ids)
        next_payment, _subscription = self._paid(self.solo, self.month, 'renewal', blocked)
        review.lines.wgs_application_state = 'review'
        blocked.order_line.filtered(lambda item: item.product_uom_qty > 0).price_unit += 1
        self.holder = self.env['res.partner'].create({'name': 'Unrelated due renewal'})
        _initial, eligible = self._paid(self.solo, self.month)
        payment, _subscription = self._paid(self.pair, self.month, 'renewal', eligible, (self.holder | self.member).ids)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 12, 16, 12)):
            self.Pos._wgs_apply_due_package_changes(limit=2)
        self.assertEqual(payment.lines.wgs_application_state, 'applied')
        self.assertEqual(review.lines.wgs_application_state, 'scheduled')
        self.assertTrue(review.lines.wgs_activation_error)
        self.assertEqual(next_payment.lines.wgs_application_state, 'scheduled')

    def test_legacy_review_is_automatically_applied_without_new_payment(self):
        _initial, subscription = self._paid(self.solo, self.month)
        payment, _subscription = self._paid(self.pair, self.month, 'renewal', subscription, (self.holder | self.member).ids)
        payment.lines.wgs_application_state = 'review'
        financial = payment.read(['amount_total', 'amount_paid', 'payment_ids'])[0]
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(payment.lines.wgs_application_state, 'applied')
        self.assertEqual(payment.read(['amount_total', 'amount_paid', 'payment_ids'])[0], financial)
        self.assertEqual(subscription._get_recurring_lines().product_id, self.pair)

    def test_inclusive_bot_close_recovers_exact_paid_source_on_first_attempt(self):
        _initial, subscription = self._paid(self.solo, self.month)
        payment, _subscription = self._paid(self.pair, self.month, 'renewal', subscription, (self.holder | self.member).ids)
        financial = payment.read(['amount_total', 'amount_paid', 'payment_ids'])[0]
        # Access-log dates use PostgreSQL's transaction timestamp, not the
        # patched business clock; readonly create_date is ignored by ORM write.
        payment.lines.flush_recordset()
        self.env.cr.execute('UPDATE pos_order_line SET create_date = %s WHERE id = %s',
                            [datetime(2026, 9, 15, 12), payment.lines.id])
        payment.lines.invalidate_recordset(['create_date'])
        # Reproduce the old core path directly, bypassing the new cron adapter.
        with patch.object(fields.Date, 'context_today', return_value=fields.Date.to_date('2026-10-15')), patch.object(
            fields.Datetime, 'now', return_value=datetime(2026, 10, 15, 20, 9),
        ):
            tracked = subscription.with_user(self.env.ref('base.user_root')).with_context(tracking_disable=False, mail_notrack=False)
            super(SaleOrderWgsLifecycle, tracked).set_close()
            tracked._track_finalize()
        # TransactionCase does not advance PostgreSQL's transaction timestamp.
        subscription.flush_recordset()
        self.env.cr.execute('UPDATE sale_order SET write_date = %s WHERE id = %s',
                            [datetime(2026, 10, 15, 20, 9), subscription.id])
        subscription.invalidate_recordset()
        tracking = self.env['mail.tracking.value'].search([
            ('field_id.model', '=', 'sale.order'), ('field_id.name', '=', 'subscription_state'),
            ('mail_message_id.model', '=', 'sale.order'), ('mail_message_id.res_id', '=', subscription.id),
            ('mail_message_id.author_id', '=', self.env.ref('base.user_root').partner_id.id),
        ], order='id desc', limit=1)
        self.assertTrue(tracking)
        tracking.mail_message_id.write({'date': datetime(2026, 10, 15, 20, 9)})
        current = self.Pos.sudo()._wgs_source_contract(subscription)
        frozen = payment.lines.wgs_activation_contract
        evidence = {
            'changed': {key: (frozen.get(key), current.get(key)) for key in current if frozen.get(key) != current.get(key)},
            'write_user': subscription.write_uid.id, 'root': self.env.ref('base.user_root').id,
            'reason': subscription.close_reason_id.display_name,
            'written': str(subscription.write_date), 'created': str(payment.lines.create_date),
            'application_date': str(payment.lines.wgs_application_date),
            'tracking_date': str(tracking.mail_message_id.date),
        }
        self.assertTrue(self.Pos.sudo()._wgs_is_automatic_inclusive_close(subscription, payment.lines), evidence)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(payment.lines.wgs_application_state, 'applied')
        self.assertTrue(payment.lines.wgs_application_receipt['automatic_close_recovered'])
        self.assertEqual(subscription.subscription_state, '3_progress')
        self.assertEqual(subscription._get_recurring_lines().product_id, self.pair)
        self.assertEqual(payment.read(['amount_total', 'amount_paid', 'payment_ids'])[0], financial)

    def test_manual_close_is_never_automatically_reopened(self):
        _initial, subscription = self._paid(self.solo, self.month)
        payment, _subscription = self._paid(self.pair, self.month, 'renewal', subscription, (self.holder | self.member).ids)
        with patch.object(fields.Date, 'context_today', return_value=fields.Date.to_date('2026-10-15')):
            subscription.set_close()
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(subscription.subscription_state, '6_churn')
        self.assertNotEqual(payment.lines.wgs_application_state, 'applied')
        self.assertEqual(payment.lines.wgs_application_state, 'scheduled')

    def test_quote_settles_due_paid_changes_before_calculating_next_period(self):
        _initial, subscription = self._paid(self.solo, self.month)
        payment, _subscription = self._paid(self.pair, self.month, 'renewal', subscription, (self.holder | self.member).ids)
        payment.lines.wgs_application_state = 'review'
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            quote = self._quote(self.pair, self.month, 'renewal', subscription)
        self.assertEqual(payment.lines.wgs_application_state, 'applied')
        self.assertEqual(quote['subscription_start_date'], '2026-11-16')
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-11-15'))

    def test_opening_customer_detail_applies_only_their_due_paid_changes(self):
        _initial, subscription = self._paid(self.solo, self.month)
        payment, _subscription = self._paid(self.pair, self.month, 'renewal', subscription, (self.holder | self.member).ids)
        payment.lines.wgs_application_state = 'review'
        original_holder = self.holder
        self.holder = self.env['res.partner'].create({'name': 'Other pending customer'})
        _other_initial, other = self._paid(self.solo, self.month)
        other_payment, _other = self._paid(self.pair, self.month, 'renewal', other)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            detail = self.Pos.wgs_get_partner_subscription_detail_for_pos(original_holder.id)
        self.assertEqual(payment.lines.wgs_application_state, 'applied')
        self.assertEqual(other_payment.lines.wgs_application_state, 'scheduled')
        item = next(item for item in detail['items'] if item['subscription_id'] == subscription.id)
        self.assertTrue(item['can_renew'])
        self.assertFalse(item['can_reenroll'])
        self.assertEqual(subscription._get_recurring_lines().product_id, self.pair)

    def test_paid_scheduled_change_is_excluded_from_close_until_activated(self):
        _initial, subscription = self._paid(self.solo, self.month)
        payment, _subscription = self._paid(self.pair, self.month, 'renewal', subscription, (self.holder | self.member).ids)
        today = fields.Date.to_date('2026-10-20')
        domain = subscription._wgs_get_subscription_auto_close_candidate_domain(today)
        self.assertNotIn(subscription, self.env['sale.order'].sudo().search(domain))
        self.assertEqual(payment.lines.wgs_application_state, 'scheduled')

    def test_same_package_renewal_preserves_current_participants(self):
        _initial, subscription = self._paid(self.pair, self.month, participants=(self.holder | self.member).ids)
        _renewal, subscription = self._paid(self.pair, self.month, 'renewal', subscription)
        self.assertEqual(set(subscription.participant_ids.ids), set((self.holder | self.member).ids))

    def test_one_hundred_percent_discount_does_not_change_plan_or_future_price(self):
        _initial, subscription = self._paid(self.solo, self.month)
        subscription.subscription_state = '6_churn'
        quarter = self.env['sale.subscription.plan'].sudo().create({
            'name': 'Complimentary quarter', 'billing_period_value': 3, 'billing_period_unit': 'month',
        })
        target = self._product('Quarter with authorized discount', quarter, 300)
        payment, subscription = self._paid(target, quarter, 'reenroll', subscription, discount=100)
        self.assertEqual(payment.amount_total, 0)
        self.assertEqual(subscription.plan_id, quarter)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-12-14'))
        self.assertEqual(subscription._get_recurring_lines().price_unit, 300)
        self.assertEqual(subscription._get_recurring_lines().discount, 0)
        quote = self._quote(target, quarter, 'renewal', subscription)
        self.assertEqual(quote['ticket_charge_now'], 300)

    def test_same_product_plan_change_waits_for_the_next_period(self):
        annual = self.env['sale.subscription.plan'].sudo().create({
            'name': 'Same product annual', 'billing_period_value': 12, 'billing_period_unit': 'month',
        })
        create_recurring_price(self.env, self.solo, annual, 1200)
        _initial, subscription = self._paid(self.solo, self.month)
        payment, subscription = self._paid(self.solo, annual, 'renewal', subscription)
        self.assertEqual(payment.lines.wgs_application_state, 'scheduled')
        self.assertEqual(subscription.plan_id, self.month)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(payment.lines.wgs_application_state, 'applied')
        self.assertEqual(subscription.plan_id, annual)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2027-10-15'))

    def test_one_run_catches_up_sequential_due_changes_within_its_budget(self):
        _initial, subscription = self._paid(self.solo, self.month)
        first, _subscription = self._paid(self.pair, self.month, 'renewal', subscription, (self.holder | self.member).ids)
        second, _subscription = self._paid(self.solo, self.month, 'renewal', subscription)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 11, 16, 12)):
            applied = self.Pos._wgs_apply_due_package_changes(limit=2)
        self.assertEqual(applied, 2)
        self.assertEqual(first.lines.wgs_application_state, 'applied')
        self.assertEqual(second.lines.wgs_application_state, 'applied')
        self.assertEqual(subscription._get_recurring_lines().product_id, self.solo)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-12-15'))

    def _native_subscription(self):
        partner = self.env['res.partner'].create({'name': 'Native backend-only subscription'})
        subscription = self.env['sale.order'].sudo().create({
            'partner_id': partner.id, 'plan_id': self.month.id,
            'order_line': [Command.create({
                'product_id': self.solo.id, 'product_uom_qty': 1, 'price_unit': 100,
            })],
        })
        subscription.action_confirm()
        subscription.write({
            'subscription_state': '3_progress', 'start_date': '2026-09-01',
            'end_date': '2026-10-15', 'next_invoice_date': '2026-10-16',
        })
        # This fixture models a backend-only subscription with no WGS access
        # snapshot; using the gym product's default snapshot makes it WGS-owned.
        subscription.with_context(wgs_skip_access_snapshot_refresh=True, wgs_defer_access_sync=True).write({
            'wgs_access_site_ids': [Command.clear()],
            'wgs_access_timezone_snapshot_id': False,
        })
        return subscription

    def test_native_invoice_domain_preserves_non_pos_subscriptions(self):
        _payment, managed = self._paid(self.solo, self.month)
        native = self._native_subscription()
        with patch.object(fields.Date, 'today', return_value=fields.Date.to_date('2026-10-15')):
            original = super(SaleOrderWgsLifecycle, self.env['sale.order'])._recurring_invoice_domain()
            self.assertIn(managed, self.env['sale.order'].search(original))
            candidates = self.env['sale.order'].search(self.env['sale.order']._recurring_invoice_domain())
        self.assertNotIn(managed, candidates)
        self.assertIn(native, candidates)

    def test_native_auto_close_cannot_expire_paid_package_change_on_inclusive_last_day(self):
        _initial, subscription = self._paid(self.solo, self.month)
        payment, _subscription = self._paid(self.pair, self.month, 'renewal', subscription, (self.holder | self.member).ids)
        before = subscription.read(['subscription_state', 'end_date', 'next_invoice_date', 'plan_id'])[0]
        with patch.object(fields.Date, 'context_today', return_value=fields.Date.to_date('2026-10-15')):
            closed = subscription._subscription_auto_close()
        self.assertFalse(closed)
        self.assertEqual(subscription.read(['subscription_state', 'end_date', 'next_invoice_date', 'plan_id'])[0], before)
        self.assertEqual(payment.lines.wgs_application_state, 'scheduled')
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(payment.lines.wgs_application_state, 'applied')
        self.assertEqual(subscription.subscription_state, '3_progress')
        self.assertEqual(subscription._get_recurring_lines().product_id, self.pair)

    def test_native_expiration_sql_rows_exclude_wgs_payments(self):
        _payment, managed = self._paid(self.solo, self.month)
        native = self._native_subscription()
        (managed | native).with_context(wgs_skip_access_snapshot_refresh=True, wgs_defer_access_sync=True).write({
            'next_invoice_date': '2026-10-01',
        })
        model = self.env['sale.order'].with_context(wgs_native_subscription_lifecycle=True)
        with patch.object(fields.Datetime, 'today', return_value=datetime(2026, 10, 20)):
            rows = model._get_expired_subscriptions()
        self.assertNotIn(managed.id, [row['so_id'] for row in rows])
        self.assertIn(native.id, [row['so_id'] for row in rows])

    def test_native_automation_context_never_changes_normal_directory_search(self):
        _payment, managed = self._paid(self.solo, self.month)
        native = self._native_subscription()
        domain = [('id', 'in', (managed | native).ids)]
        automatic = self.env['sale.order'].with_context(wgs_native_subscription_lifecycle=True).search(domain)
        self.assertEqual(automatic, native)
        self.assertEqual(set(self.env['sale.order'].search(domain).ids), set((managed | native).ids))

    def test_explicit_all_wgs_invoice_batch_cannot_expand_to_global_search(self):
        _payment, managed = self._paid(self.solo, self.month)
        self._native_subscription()
        records, retrigger = managed.with_context(wgs_native_subscription_lifecycle=True)._recurring_invoice_get_subscriptions()
        self.assertEqual(records, [])
        self.assertFalse(retrigger)

    def test_manual_native_close_is_preserved_but_automatic_close_skips_wgs(self):
        _payment, managed = self._paid(self.solo, self.month)
        managed.with_context(wgs_native_subscription_lifecycle=True).set_close()
        self.assertEqual(managed.subscription_state, '3_progress')
        managed.set_close()
        self.assertEqual(managed.subscription_state, '6_churn')

    def test_wgs_auto_close_does_not_take_over_native_only_contracts(self):
        self.month.auto_close_limit = 3
        _payment, managed = self._paid(self.solo, self.month)
        native = self._native_subscription()
        today = fields.Date.to_date('2026-10-20')
        candidates = self.env['sale.order'].sudo().search(
            self.env['sale.order']._wgs_get_subscription_auto_close_candidate_domain(today),
        )
        self.assertIn(managed, candidates)
        self.assertNotIn(native, candidates)

    def test_future_package_and_participants_wait_until_paid_period_ends(self):
        _order, subscription = self._paid(self.solo, self.month)
        renewal, _subscription = self._paid(
            self.pair, self.month, 'renewal', subscription, (self.holder | self.member).ids,
        )
        self.assertEqual(renewal.lines.wgs_application_state, 'scheduled')
        self.assertEqual(subscription._get_recurring_lines().product_id, self.solo)
        self.assertNotIn(self.member, subscription.participant_ids)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-15'))
        self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(renewal.lines.wgs_application_state, 'scheduled')
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            self.Pos._wgs_apply_due_package_changes()
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(renewal.lines.wgs_application_state, 'applied')
        self.assertEqual(subscription._get_recurring_lines().product_id, self.pair)
        self.assertIn(self.member, subscription.participant_ids)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-11-15'))
        self.assertEqual(subscription.wgs_monthly_cutoff_day, 15)

    def test_month_end_cutoff_survives_multiple_advance_payments_and_replays(self):
        with patch.object(fields.Datetime, 'now', return_value=datetime(2027, 1, 31, 12)):
            _order, subscription = self._paid(self.solo, self.month, start='2027-01-31')
            self.assertEqual(subscription.end_date, fields.Date.to_date('2027-02-28'))
            for start, end in (
                ('2027-03-01', '2027-03-31'), ('2027-04-01', '2027-04-30'),
                ('2027-05-01', '2027-05-31'),
            ):
                quote = self._quote(self.solo, self.month, 'renewal', subscription)
                self.assertEqual(quote['subscription_start_date'], start)
                self.assertEqual(quote['subscription_end_date'], end)
                self.assertEqual(quote['commercial_quote']['payload']['pricing']['monthly_cutoff_day'], 31)
                order, _subscription = self._paid(self.solo, self.month, 'renewal', subscription)
                order._wgs_sync_subscription_sales()
                self.assertEqual(subscription.end_date, fields.Date.to_date(end))
                self.assertEqual(subscription.wgs_monthly_cutoff_day, 31)

    def test_pre_upgrade_queued_quote_keeps_its_paid_dates(self):
        def legacy_schedule(records, plan, start_date, **kwargs):
            end = records._wgs_get_plan_period_end_date(plan, start_date)
            return {
                'subscription_end_date': end,
                'next_billing_date': records._wgs_get_plan_min_end_threshold(plan, start_date),
                'monthly_cutoff_day': 0,
            }

        def legacy_contract(records, pricing, request, plan):
            return {
                'version': 1, 'mode': 'term', 'start': pricing['subscription_start_date'],
                'interval': 1, 'unit': 'month', 'aligned': False, 'cutoff': 0, 'previous_end': False,
            }

        with patch.object(type(self.Pos), '_wgs_get_sale_period_schedule', legacy_schedule), \
                patch.object(type(self.Pos), '_wgs_build_period_contract', legacy_contract):
            _order, subscription = self._paid(self.solo, self.month)
            queued, _subscription = self._paid(
                self.pair, self.month, 'renewal', subscription, (self.holder | self.member).ids,
            )
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-14'))
        self.assertEqual(subscription.wgs_monthly_cutoff_day, 0)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 15, 12)):
            self.Pos._wgs_apply_due_package_changes()
            self.assertEqual(queued.lines.wgs_application_state, 'applied')
            self.assertEqual(subscription.end_date, fields.Date.to_date('2026-11-14'))
            quote = self._quote(self.pair, self.month, 'renewal', subscription)
        self.assertEqual(quote['subscription_start_date'], '2026-11-15')
        self.assertEqual(quote['subscription_end_date'], '2026-12-15')
        self.assertEqual(quote['monthly_cutoff_day'], 15)

    def test_invalid_monthly_duration_is_rejected_before_any_paid_order(self):
        OrderType = type(self.Pos)
        original = OrderType._wgs_build_product_pricing_payload_for_pos

        def wrong_duration(records, *args, **kwargs):
            result = original(records, *args, **kwargs)
            return {**result, 'subscription_end_date': '2026-12-15', 'next_billing_date': '2026-12-16'}

        before = self.Pos.search_count([('partner_id', '=', self.holder.id)])
        with patch.object(OrderType, '_wgs_build_product_pricing_payload_for_pos', wrong_duration):
            with self.assertRaises(UserError):
                self._paid(self.solo, self.month)
        self.assertEqual(self.Pos.search_count([('partner_id', '=', self.holder.id)]), before)

    def test_cancelled_native_result_rolls_back_the_whole_payment(self):
        OrderType = type(self.Pos)
        original = OrderType._wgs_create_subscription_sale_order_from_line

        def closed_result(records, line):
            result = original(records, line)
            result.write({'subscription_state': '6_churn'})
            return result

        before = self.Pos.search_count([('partner_id', '=', self.holder.id)])
        with self.assertRaises(UserError), self.env.cr.savepoint():
            with patch.object(OrderType, '_wgs_create_subscription_sale_order_from_line', closed_result):
                self._paid(self.solo, self.month)
        self.assertEqual(self.Pos.search_count([('partner_id', '=', self.holder.id)]), before)

    def _check_current_participant_edit_before_paid_activation(self, legacy=False):
        _order, subscription = self._paid(self.pair, self.month, participants=(self.holder | self.member).ids)
        renewal, _subscription = self._paid(self.solo, self.month, 'renewal', subscription)
        line = renewal.lines
        if legacy:
            line.wgs_activation_contract = False
        paid_hash, period = line.wgs_application_hash, subscription.end_date
        replacement = self.env['res.partner'].create({'name': 'Edited current member'})
        self.env['sale.order'].wgs_update_subscription_participants_for_pos(
            subscription.id, (self.holder | replacement).ids,
        )
        self.assertTrue(line.wgs_activation_contract)
        self.assertEqual(subscription.end_date, period)
        self.assertEqual(line.wgs_application_hash, paid_hash)
        self.assertEqual(line.wgs_get_participant_ids(), self.holder.ids)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(line.wgs_application_state, 'applied')
        self.assertFalse(line.wgs_activation_error)
        self.assertEqual(subscription.participant_ids, self.holder)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-11-15'))
        self.assertEqual(line.wgs_application_hash, paid_hash)

    def test_current_participants_can_change_without_blocking_paid_future_package(self):
        self._check_current_participant_edit_before_paid_activation()

    def test_legacy_queue_freezes_only_its_matching_revision_before_participant_edit(self):
        self._check_current_participant_edit_before_paid_activation(legacy=True)

    def test_silent_access_failure_keeps_recovery_pending_without_replaying_payment(self):
        with patch.object(type(self.env['sale.order']), '_wgs_get_access_site_ids', return_value=[]):
            order, subscription = self._paid(self.solo, self.month)
        self.assertEqual(order.lines.wgs_application_state, 'applied')
        self.assertTrue(order.wgs_access_sync_pending)
        payments = order.payment_ids.read(['amount', 'payment_method_id'])
        end = subscription.end_date
        order._wgs_finalize_paid_access(subscription, self.holder.ids)
        self.assertFalse(order.wgs_access_sync_pending)
        self.assertEqual(order.payment_ids.read(['amount', 'payment_method_id']), payments)
        self.assertEqual(subscription.end_date, end)
        self.assertEqual(subscription._wgs_get_access_profile_for_partner(self.holder)['access_state'], 'enabled')

    def test_paid_renewal_leaves_native_renew_state_and_enables_access(self):
        _order, subscription = self._paid(self.solo, self.month)
        renewal_state = next((value for value, _label in
                              subscription._fields['subscription_state']._description_selection(self.env)
                              if subscription._wgs_get_subscription_state_category_from_value(value) == 'renew'), False)
        if not renewal_state:
            self.skipTest('This native schema has no renewable subscription state.')
        subscription.write({'subscription_state': renewal_state})
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            order, subscription = self._paid(self.solo, self.month, 'renewal', subscription)
        self.assertEqual(subscription._wgs_get_subscription_state_category(), 'progress')
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-11-15'))
        self.assertFalse(order.wgs_access_sync_pending)

    def test_reenrollment_from_old_holder_contract_rejects_another_active_membership(self):
        _order, subscription = self._paid(self.solo, self.month)
        old = subscription.copy({'state': 'sale', 'subscription_state': '6_churn',
                                 'start_date': '2026-05-01', 'wgs_effective_start_date': '2026-05-01',
                                 'end_date': '2026-05-31', 'next_invoice_date': '2026-06-01'})
        with self.assertRaises(UserError):
            self._quote(self.solo, self.month, 'reenroll', old)
        self.assertEqual(subscription.subscription_state, '3_progress')

    def test_ticket_preflight_rejects_two_new_contracts_without_buffer_or_payment(self):
        configs, lines = [], []
        for product in (self.solo, self.pair):
            quote = self._quote(product, self.month)
            uid = str(uuid4())
            configs.append({'line_uuid': uid, 'product_id': product.id, 'quantity': 1,
                            'flow': 'new', 'participant_ids': self.holder.ids,
                            'pricing_snapshot': quote})
            lines.append({'uuid': uid, 'product_id': product.id, 'qty': 1,
                          'price_unit': quote['ticket_charge_now'], 'discount': 0})
        uid = str(uuid4())
        with self.assertRaises(UserError):
            self.Pos.wgs_stage_subscription_config_for_uuid(uid, configs, {
                'partner_id': self.holder.id, 'company_id': self.env.company.id, 'lines': lines,
            })
        self.assertFalse(self.env['wgs.pos.subscription.buffer'].sudo().search([('order_uuid', '=', uid)]))

    def test_directory_counts_omit_unrelated_contacts_from_business_classification(self):
        _order, _subscription = self._paid(self.solo, self.month)
        Order = self.env['sale.order']
        before = Order.get_partner_directory_summary_for_pos({'company_id': self.env.company.id})
        unrelated = self.env['res.partner'].create([{'name': 'No subscription QA %s' % i} for i in range(25)])
        called = set()
        original = type(Order)._get_partner_subscription_directory_status_map_for_pos

        def record_batch(records, partners, *args, **kwargs):
            called.update(partners.ids)
            return original(records, partners, *args, **kwargs)

        with patch.object(type(Order), '_get_partner_subscription_directory_status_map_for_pos', record_batch):
            after = Order.get_partner_directory_summary_for_pos({'company_id': self.env.company.id})
        self.assertFalse(called.intersection(unrelated.ids))
        self.assertEqual(after['total'] - before['total'], len(unrelated))
        self.assertEqual(after['none'] - before['none'], len(unrelated))

    def test_semester_to_month_uses_catalog_plan_and_defers_application(self):
        semester = self.env['sale.subscription.plan'].sudo().create({
            'name': 'Semester contract test', 'billing_period_value': 6, 'billing_period_unit': 'month',
        })
        semester_product = self._product('Semester', semester, 600)
        _initial, subscription = self._paid(semester_product, semester, start='2026-05-14')
        # Changing package in the POS sends no inherited plan/pricing preference.
        quote = self.Pos.wgs_get_subscription_quote_for_pos(
            partner_id=self.holder.id, product_id=self.solo.id, flow='renewal',
            source_subscription_id=subscription.id,
        )['pricing']
        self.assertEqual(quote['plan_id'], self.month.id)
        self.assertEqual(quote['interval_value'], 1)
        self.assertEqual(quote['interval_unit'], 'month')
        self.assertEqual(quote['ticket_charge_now'], 100)
        self.assertEqual(quote['subscription_start_date'], '2026-11-14')
        self.assertEqual(quote['subscription_end_date'], '2026-12-14')
        self.assertEqual(quote['next_billing_date'], '2026-12-15')
        self.assertTrue(quote['commercial_quote']['signature'])

        renewal, result = self._paid(self.solo, False, 'renewal', subscription)
        self.assertEqual(result, subscription)
        self.assertEqual(renewal.lines.wgs_application_state, 'scheduled')
        self.assertEqual(subscription.plan_id, semester)
        self.assertEqual(subscription._get_recurring_lines().product_id, semester_product)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-11-13'))
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 11, 14, 12)):
            self.Pos._wgs_apply_due_package_changes()
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(renewal.lines.wgs_application_state, 'applied')
        self.assertEqual(subscription.plan_id, self.month)
        self.assertEqual(subscription._get_recurring_lines().product_id, self.solo)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-12-14'))
        renewal._wgs_sync_subscription_sales()
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-12-14'))

    def test_quarter_to_month_applies_only_the_purchased_month(self):
        quarter = self.env['sale.subscription.plan'].sudo().create({
            'name': 'Quarterly source', 'billing_period_value': 3, 'billing_period_unit': 'month',
        })
        quarterly_product = self._product('Quarterly package', quarter, 300)
        _initial, subscription = self._paid(quarterly_product, quarter, start='2026-07-03')
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-02'))
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 3, 18)):
            quote = self._quote(self.solo, False, 'renewal', subscription)
            self.assertEqual(quote['plan_id'], self.month.id)
            self.assertEqual(quote['ticket_charge_now'], 100)
            self.assertEqual(quote['subscription_start_date'], '2026-10-03')
            self.assertEqual(quote['subscription_end_date'], '2026-11-03')
            renewal, result = self._paid(self.solo, False, 'renewal', subscription)
        self.assertEqual(result, subscription)
        self.assertEqual(renewal.lines.wgs_application_state, 'applied')
        self.assertEqual(subscription.plan_id, self.month)
        self.assertEqual(subscription._get_recurring_lines().product_id, self.solo)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-11-03'))
        self.assertEqual(subscription.next_invoice_date, fields.Date.to_date('2026-11-04'))
        receipt = renewal.lines.wgs_application_receipt
        renewal._wgs_sync_subscription_sales()
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-11-03'))
        self.assertEqual(renewal.lines.wgs_application_receipt, receipt)

    def test_aligned_reenrollment_prorates_same_and_other_package(self):
        _order, subscription = self._paid(self.solo, self.month)
        subscription.write({'subscription_state': '6_churn'})
        alignment_field = self.Pos._wgs_get_period_alignment_field_name(self.month)
        self.assertTrue(alignment_field)
        self.month.write({alignment_field: True})
        for product, amount in ((self.solo, 100), (self.pair, 180)):
            quote = self._quote(product, self.month, 'reenroll', subscription)
            self.assertEqual(quote['charge_now'], round(amount * 16 / 30, 2))
            self.assertEqual(quote['subscription_start_date'], '2026-09-15')
            self.assertEqual(quote['subscription_end_date'], '2026-09-30')

    def test_two_future_renewals_keep_their_own_package_and_participants(self):
        _order, subscription = self._paid(self.solo, self.month)
        first, _subscription = self._paid(
            self.pair, self.month, 'renewal', subscription, (self.holder | self.member).ids,
        )
        second_member = self.env['res.partner'].create({'name': 'Next period participant'})
        second, _subscription = self._paid(
            self.pair, self.month, 'renewal', subscription, (self.holder | second_member).ids,
        )
        item = subscription._build_pos_subscription_status_item(fields.Date.to_date('2026-09-15'))
        self.assertEqual(item['renewal_product_id'], self.solo.id)
        self.assertEqual(item['renewal_defaults']['product_id'], self.pair.id)
        self.assertEqual(item['renewal_defaults']['plan_id'], self.month.id)
        self.assertEqual(set(item['renewal_defaults']['participant_ids']), set((self.holder | second_member).ids))
        self.assertEqual(second.lines.wgs_application_date, fields.Date.to_date('2026-11-16'))
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(first.lines.wgs_application_state, 'applied')
        self.assertEqual(second.lines.wgs_application_state, 'scheduled')
        self.assertIn(self.member, subscription.participant_ids)
        self.assertNotIn(second_member, subscription.participant_ids)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 11, 16, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(second.lines.wgs_application_state, 'applied')
        self.assertIn(second_member, subscription.participant_ids)
        self.assertNotIn(self.member, subscription.participant_ids)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-12-15'))

    def test_refund_rejects_partial_and_accepts_full_once(self):
        order, subscription = self._paid(self.solo, self.month)
        original = order.lines
        with self.assertRaises(UserError):
            order._wgs_validate_full_membership_refund(original, -0.5, original.price_unit, 0)
        refund, _unused = self.create_backend_pos_order({
            'order_data': {'partner_id': self.holder.id, 'state': 'paid'},
            'line_data': [{
                'product_id': self.solo.id, 'qty': -1, 'price_unit': original.price_unit,
                'refunded_orderline_id': original.id,
            }],
        })
        refund._wgs_sync_subscription_sales()
        refund._wgs_sync_subscription_sales()
        self.assertTrue(order._wgs_is_subscription_order_closed_for_reenroll(subscription))
        with self.assertRaises(UserError):
            order._wgs_validate_full_membership_refund(original, -1, original.price_unit, 0)

    def test_access_failure_does_not_replay_commercial_operation(self):
        OrderType = type(self.env['sale.order'])
        original = OrderType._wgs_update_access_snapshot

        def fail_final_projection(records, *args, **kwargs):
            if not records.env.context.get('wgs_defer_access_sync'):
                raise UserError('test projection failure')
            return original(records, *args, **kwargs)

        with patch.object(OrderType, '_wgs_update_access_snapshot', fail_final_projection):
            order, subscription = self._paid(self.solo, self.month)
        self.assertTrue(order.wgs_access_sync_pending)
        self.assertEqual(order.lines.wgs_application_state, 'applied')
        end = subscription.end_date
        order._wgs_sync_subscription_sales()
        order._wgs_finalize_paid_access(subscription, self.holder.ids)
        self.assertFalse(order.wgs_access_sync_pending)
        self.assertEqual(subscription.end_date, end)

    def test_zero_recurring_price_is_not_replaced_by_ticket_price(self):
        order, _subscription = self._paid(self.solo, self.month)
        line = self.env['pos.order.line'].new({
            'product_id': self.solo.id, 'qty': 1, 'price_unit': 99,
            'wgs_subscription_plan_id': self.month.id,
            'wgs_pricing_snapshot_json': json.dumps({'recurring_price': 0}),
        })
        self.assertEqual(order._wgs_get_persisted_subscription_pricing_from_pos_line(line)['price_unit'], 0)

    def test_historical_period_repair_requires_explicit_start_and_current_approval(self):
        order, subscription = self._paid(self.solo, self.month)
        options = {'plan_id': self.month.id, 'source_subscription_id': subscription.id}
        with self.assertRaises(UserError):
            order._wgs_prepare_period_repair(order.lines, options)
        options['start_date'] = '2026-09-15'
        proposal = order._wgs_prepare_period_repair(order.lines, options)
        self.assertEqual(proposal['end_date'], '2026-10-14')
        with self.assertRaises(UserError):
            order._wgs_apply_approved_period_repair(order.lines, options)
        options['approval_digest'] = order._wgs_period_repair_digest(proposal)
        subscription.end_date = fields.Date.to_date('2026-10-01')
        with self.assertRaises(UserError):
            order._wgs_apply_approved_period_repair(order.lines, options)

    def _historical_domiciliation(self):
        self.month.write({'wgs_domiciliation_enabled': True, 'wgs_domiciliation_term_months': 12})
        tax = create_tax(self.env, {
            'name': 'Incident VAT 16%', 'amount': 16, 'amount_type': 'percent',
            'company_id': self.env.company.id, 'type_tax_use': 'sale',
        })
        self.solo.taxes_id = tax
        price = self.env['product.pricelist.item'].search([
            ('product_tmpl_id', '=', self.solo.product_tmpl_id.id), ('plan_id', '=', self.month.id),
        ])
        price.fixed_price = 533.62
        initial, sub = self._paid(self.solo, self.month, start='2026-09-01', months=[1])
        self.assertEqual(initial.amount_total, 619)
        price.fixed_price = 533.63
        sub.subscription_state = '6_churn'
        return initial, sub, sub.wgs_domiciliation_contract_id

    def test_domiciliation_collection_uses_frozen_price_with_vat_and_replay_is_idempotent(self):
        initial, sub, contract = self._historical_domiciliation()
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 28, 12)):
            quote = self._quote(self.solo, self.month, 'renewal', sub, months=[2])
            self.assertEqual(quote['recurring_price'], 533.62)
            self.assertEqual(quote['ticket_charge_now'], 533.62)
            self.assertEqual(quote['display_charge_now'], 619)
            before = self.Pos._wgs_domiciliation_collection_state(sub, selected_sequences=[2])
            payment, result = self._paid(self.solo, self.month, 'renewal', sub, months=[2])
            self.assertEqual(result, sub)
            self.assertEqual(payment.amount_total, 619)
            self.assertEqual(payment.lines.price_unit, 533.62)
            self.assertEqual(self.Pos._wgs_domiciliation_collection_state(sub, selected_sequences=[2]), before)
            self.assertEqual(sub.subscription_state, '6_churn')
            self.assertTrue(contract.is_access_current)
            self.assertEqual(contract.term_end_date, fields.Date.to_date('2027-08-31'))
            paid = contract.installment_ids.filtered(lambda i: i.sequence == 2)
            self.assertEqual(paid.paid_pos_line_id, payment.lines)
            receipt = payment.lines.wgs_application_receipt
            old_payments = initial.payment_ids.read(['amount', 'pos_order_id'])
            payment._wgs_sync_subscription_sales()
            self.assertEqual(payment.lines.wgs_application_receipt, receipt)
            self.assertEqual(paid.paid_pos_line_id, payment.lines)
            self.assertEqual(initial.payment_ids.read(['amount', 'pos_order_id']), old_payments)
            self.assertEqual(sum(payment.payment_ids.mapped('amount')), 619)

    def test_domiciliation_collection_preserves_legacy_discounted_native_representation(self):
        _initial, sub, contract = self._historical_domiciliation()
        sub.order_line.write({'price_unit': 0, 'discount': 100})
        before = self.Pos._wgs_domiciliation_collection_state(sub, selected_sequences=[2])
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 28, 12)):
            payment, _sub = self._paid(self.solo, self.month, 'renewal', sub, months=[2])
        self.assertEqual(payment.amount_total, 619)
        self.assertEqual(sub.order_line.price_unit, 0)
        self.assertEqual(sub.order_line.discount, 100)
        self.assertEqual(contract.monthly_amount, 533.62)
        self.assertEqual(self.Pos._wgs_domiciliation_collection_state(sub, selected_sequences=[2]), before)

    def test_domiciliation_collection_preserves_a_different_legacy_native_plan(self):
        initial, sub, contract = self._historical_domiciliation()
        legacy = self.env['sale.subscription.plan'].sudo().create({
            'name': 'Historical monthly plan, not the wallet plan',
            'billing_period_value': 1, 'billing_period_unit': 'month',
        })
        sub.write({'plan_id': legacy.id})
        before = self.Pos._wgs_domiciliation_collection_state(sub, selected_sequences=[2])
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 28, 18)):
            payment, result = self._paid(self.solo, self.month, 'renewal', sub, months=[2])
            self.assertEqual(result, sub)
            self.assertEqual(payment.lines.wgs_application_state, 'applied')
            self.assertEqual(payment.amount_total, 619)
            receipt = payment.lines.wgs_application_receipt
            payment._wgs_sync_subscription_sales()
            self.assertEqual(payment.lines.wgs_application_receipt, receipt)
        self.assertEqual(sub.plan_id, legacy)
        self.assertEqual(contract.plan_id, self.month)
        self.assertEqual(self.Pos._wgs_domiciliation_collection_state(sub, selected_sequences=[2]), before)
        self.assertEqual(contract.installment_ids.filtered(lambda i: i.sequence == 1).paid_pos_order_id, initial)
        self.assertEqual(contract.installment_ids.filtered(lambda i: i.sequence == 2).paid_pos_order_id, payment)

    def test_domiciliation_collection_rolls_back_a_native_plan_rewrite(self):
        _initial, sub, contract = self._historical_domiciliation()
        legacy = self.env['sale.subscription.plan'].sudo().create({
            'name': 'Preserved native plan', 'billing_period_value': 1, 'billing_period_unit': 'month',
        })
        sub.write({'plan_id': legacy.id})
        before = self.Pos._wgs_domiciliation_collection_state(sub, selected_sequences=[2])
        original = type(self.Pos)._wgs_process_subscription_renewal_line

        def rewrite_native_plan(order, line, **kwargs):
            result = original(order, line, **kwargs)
            result.write({'plan_id': contract.plan_id.id})
            return result

        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 28, 18)):
            with patch.object(type(self.Pos), '_wgs_process_subscription_renewal_line', rewrite_native_plan):
                with self.assertRaises(UserError), self.env.cr.savepoint():
                    self._paid(self.solo, self.month, 'renewal', sub, months=[2])
        self.env.invalidate_all()
        self.assertEqual(sub.plan_id, legacy)
        self.assertEqual(self.Pos._wgs_domiciliation_collection_state(sub, selected_sequences=[2]), before)

    def test_domiciliation_postcondition_failure_rolls_back_payment_and_installments(self):
        _initial, sub, contract = self._historical_domiciliation()
        ledger = contract.installment_ids.read(['amount', 'state', 'paid_pos_line_id', 'paid_pos_order_id', 'paid_at'])
        orders_before = self.Pos.search_count([('partner_id', '=', self.holder.id)])
        original = type(self.Pos)._wgs_assert_domiciliation_application

        def fail_after_wallet_payment(records, *args):
            original(records, *args)
            raise UserError('Reject incomplete wallet application')

        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 28, 12)):
            with patch.object(type(self.Pos), '_wgs_assert_domiciliation_application', fail_after_wallet_payment):
                with self.assertRaises(UserError), self.env.cr.savepoint():
                    self._paid(self.solo, self.month, 'renewal', sub, months=[2])
            self.assertEqual(contract.installment_ids.read(['amount', 'state', 'paid_pos_line_id', 'paid_pos_order_id', 'paid_at']), ledger)
            self.assertEqual(self.Pos.search_count([('partner_id', '=', self.holder.id)]), orders_before)
            payment, _sub = self._paid(self.solo, self.month, 'renewal', sub, months=[2])
            self.assertEqual(payment.amount_total, 619)

    def test_domiciliation_restart_preserves_previous_installments(self):
        self.month.write({'wgs_domiciliation_enabled': True, 'wgs_domiciliation_term_months': 12})
        _order, subscription = self._paid(self.solo, self.month, start='2026-02-15', months=[1, 12])
        old = subscription.wgs_domiciliation_contract_id
        old_ids = old.installment_ids.ids
        paid_ids = old.installment_ids.filtered(lambda item: item.state == 'paid').ids
        old.state = 'cancelled'
        subscription.write({'subscription_state': '6_churn'})
        _reenroll, subscription = self._paid(self.solo, self.month, 'reenroll', subscription, months=[1])
        self.assertNotEqual(subscription.wgs_domiciliation_contract_id, old)
        self.assertEqual(old.installment_ids.ids, old_ids)
        self.assertEqual(old.installment_ids.filtered(lambda item: item.state == 'paid').ids, paid_ids)
        self.assertEqual(old.state, 'cancelled')

    def test_legacy_domiciliation_schedules_one_initial_cycle(self):
        _order, subscription = self._paid(self.solo, self.month)
        self.month.write({'wgs_domiciliation_enabled': True, 'wgs_domiciliation_term_months': 12})
        order, _subscription = self._paid(self.solo, self.month, 'renewal', subscription, months=[1, 2])
        self.assertEqual(order.lines.wgs_application_state, 'scheduled')
        self.assertFalse(subscription.wgs_domiciliation_contract_id)
        with self.assertRaises(UserError):
            self._quote(self.solo, self.month, 'renewal', subscription)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(order.lines.wgs_application_state, 'applied')
        contract = subscription.wgs_domiciliation_contract_id
        self.assertEqual(contract.state, 'active')
        self.assertEqual(contract.installment_ids.filtered(lambda item: item.state == 'paid').mapped('sequence'), [1, 2])

    def test_cancelled_upsale_does_not_hide_a_reactivated_paid_source(self):
        _initial, source = self._paid(self.solo, self.month)
        _upgrade, target = self._paid(self.pair, self.month, 'upsale', source, (self.holder | self.member).ids)
        self.assertTrue(source._wgs_has_replacement_subscription_for_pos())
        target.action_cancel()
        self.Pos._wgs_reactivate_subscription_order_for_pos(source)
        self.assertFalse(source._wgs_has_replacement_subscription_for_pos())
        row = self.Pos.wgs_get_partner_directory_row_for_pos(self.holder.id, source.company_id.id)
        self.assertEqual(row['subscription_id'], source.id)
        self.assertEqual(row['state'], 'progress')

    def test_monthly_to_different_domiciliation_package_waits_for_paid_period(self):
        _initial, source = self._paid(self.solo, self.month)
        plan = self.month.copy({'name': 'New domiciliation', 'wgs_domiciliation_enabled': True,
                                'wgs_domiciliation_term_months': 12})
        target = self._product('Domiciliation destination', plan, 70)
        renewal, result = self._paid(target, plan, 'renewal', source, months=[1, 12])
        self.assertEqual(result, source)
        self.assertEqual(source.plan_id, self.month)
        self.assertFalse(source.wgs_domiciliation_contract_id)
        self.assertEqual(renewal.lines.wgs_application_state, 'scheduled')
        self.assertEqual(renewal.amount_total, 106.13)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 16, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(renewal.lines.wgs_application_state, 'applied')
        self.assertEqual(source.plan_id, plan)
        self.assertEqual(source.wgs_domiciliation_contract_id.product_id, target)
        self.assertEqual(source.wgs_domiciliation_contract_id.installment_ids.filtered(
            lambda item: item.state == 'paid').mapped('sequence'), [1, 12])

    def _full_refund(self, payment):
        original = payment.lines
        refund, _unused = self.create_backend_pos_order({
            'order_data': {'partner_id': self.holder.id, 'state': 'paid'},
            'line_data': [{'product_id': original.product_id.id, 'qty': -1,
                           'price_unit': original.price_unit, 'discount': original.discount,
                           'refunded_orderline_id': original.id}],
        })
        refund._wgs_sync_subscription_sales()
        return refund

    def test_full_membership_refund_closes_invoiced_subscription_without_cancelling_invoices(self):
        payment, source = self._paid(self.solo, self.month)
        # A historical invoice predates the POS event. Do not change today's
        # recurring invoice eligibility merely to build the incident fixture.
        values = source._prepare_invoice()
        values['invoice_line_ids'] = [Command.create(source._get_recurring_lines()._prepare_invoice_line())]
        invoices = self.env['account.move'].create(values)
        self.assertTrue(invoices)
        before = invoices.read(['state', 'amount_total', 'payment_state'])
        refund = self._full_refund(payment)
        self.assertEqual(refund.lines.wgs_application_state, 'applied')
        self.assertEqual(source.subscription_state, '6_churn')
        self.assertEqual(invoices.read(['state', 'amount_total', 'payment_state']), before)
        self.assertFalse(source._wgs_subscription_operation_policy_for_pos()['access_state'])

    def test_full_domiciliation_collection_refund_reverses_only_its_months_once(self):
        _initial, source, contract = self._historical_domiciliation()
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 5, 12)):
            payment, _source = self._paid(self.solo, self.month, 'renewal', source, months=[2], discount=50)
            before = self.Pos._wgs_domiciliation_collection_state(source, selected_sequences=[2])
            financial = payment.payment_ids.read(['amount', 'payment_method_id'])
            refund = self._full_refund(payment)
            self.assertEqual(refund.lines.wgs_application_state, 'applied')
            self.assertEqual(contract.state, 'active')
            self.assertEqual(self.Pos._wgs_domiciliation_collection_state(source, selected_sequences=[2]), before)
            self.assertEqual(contract.installment_ids.filtered(lambda item: item.sequence == 2).state, 'due')
            self.assertEqual(payment.payment_ids.read(['amount', 'payment_method_id']), financial)
            self.assertFalse(contract.is_access_current)
            refund._wgs_sync_subscription_sales()
            with self.assertRaises(UserError), self.env.cr.savepoint():
                self._full_refund(payment)
            recollection, _source = self._paid(self.solo, self.month, 'renewal', source, months=[2])
            self.assertEqual(recollection.amount_total, 619)
            self.assertTrue(contract.is_access_current)

    def test_legacy_paid_activation_recovery_is_explicit_and_preserves_the_payment(self):
        _initial, source = self._paid(self.solo, self.month)
        annual = self.month.copy({'name': 'Recovered annual', 'billing_period_value': 12})
        target = self._product('Recovered annual package', annual, 1200)
        payment, _source = self._paid(target, annual, 'renewal', source)
        payment.lines.wgs_activation_contract = False
        source.order_line.filtered(lambda item: item.product_uom_qty > 0).name = 'Historical edit'
        source.wgs_monthly_cutoff_day = 14
        financial = payment.read(['amount_total', 'amount_paid', 'payment_ids'])[0]
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 20, 12)):
            self.Pos._wgs_apply_due_package_changes()
            self.assertEqual(payment.lines.wgs_application_state, 'scheduled')
            proposal = self.Pos.wgs_recover_paid_activation_for_pos(payment.lines.id)
            self.assertEqual(payment.lines.wgs_application_state, 'scheduled')
            with self.assertRaises(UserError), self.env.cr.savepoint():
                self.Pos.wgs_recover_paid_activation_for_pos(payment.lines.id, 'incorrect', dry_run=False)
            result = self.Pos.wgs_recover_paid_activation_for_pos(
                payment.lines.id, proposal['approval_digest'], dry_run=False,
            )
        self.assertEqual(result['state'], 'applied')
        self.assertEqual(source.plan_id, annual)
        self.assertEqual(source.end_date, fields.Date.to_date('2027-10-15'))
        self.assertEqual(payment.read(['amount_total', 'amount_paid', 'payment_ids'])[0], financial)
        self.assertTrue(payment.lines.wgs_application_receipt['approved_recovery'])
        with self.assertRaises(UserError):
            self.Pos.wgs_recover_paid_activation_for_pos(payment.lines.id)

    def test_paid_activation_recovery_rejects_changed_paid_line_and_non_manager(self):
        _initial, source = self._paid(self.solo, self.month)
        payment, _source = self._paid(self.pair, self.month, 'renewal', source, (self.holder | self.member).ids)
        with self.assertRaises(UserError):
            self.Pos.with_user(self.env.ref('base.public_user')).wgs_recover_paid_activation_for_pos(payment.lines.id)
        payment.lines.price_unit += 1
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 20, 12)):
            with self.assertRaisesRegex(UserError, 'contenido del pago'):
                self.Pos.wgs_recover_paid_activation_for_pos(payment.lines.id)

    def test_paid_activation_recovery_approval_expires_when_source_changes(self):
        _initial, source = self._paid(self.solo, self.month)
        payment, _source = self._paid(self.pair, self.month, 'renewal', source, (self.holder | self.member).ids)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 20, 12)):
            proposal = self.Pos.wgs_recover_paid_activation_for_pos(payment.lines.id)
            source.wgs_monthly_cutoff_day = 14
            with self.assertRaisesRegex(UserError, 'propuesta cambio'), self.env.cr.savepoint():
                self.Pos.wgs_recover_paid_activation_for_pos(payment.lines.id, proposal['approval_digest'], dry_run=False)
        self.assertEqual(payment.lines.wgs_application_state, 'scheduled')
        self.assertEqual(source._get_recurring_lines().product_id, self.solo)

    def test_paid_activation_recovery_never_overwrites_a_later_paid_purchase(self):
        _initial, source = self._paid(self.solo, self.month)
        first, _source = self._paid(self.pair, self.month, 'renewal', source, (self.holder | self.member).ids)
        self._paid(self.solo, self.month, 'renewal', source)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 20, 12)):
            with self.assertRaisesRegex(UserError, 'pago posterior'):
                self.Pos.wgs_recover_paid_activation_for_pos(first.lines.id)
