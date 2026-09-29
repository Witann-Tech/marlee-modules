"""Commercial integration gate. Run on a disposable Odoo 19 Enterprise database."""

import json
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged('post_install', '-at_install', 'wgs_commercial')
class TestSubscriptionOperations(CommonPosTest):
    def setUp(self):
        super().setUp()
        self.Pos = self.env['pos.order']
        self.clock = patch.object(fields.Datetime, 'now', return_value=datetime(2026, 9, 15, 12))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.holder = self.env['res.partner'].create({'name': 'Commercial flow holder'})
        self.member = self.env['res.partner'].create({'name': 'Commercial flow participant'})
        self.month = self.env['sale.subscription.plan'].create({
            'name': 'Monthly contract test', 'billing_period_value': 1, 'billing_period_unit': 'month',
        })
        self.day = self.env['sale.subscription.plan'].create({
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
            'available_in_pos': True, 'list_price': amount, 'taxes_id': [Command.clear()],
            'max_participants_total': capacity,
        })
        Pricing = self.env['sale.subscription.pricing']
        # The test must fail, not silently skip, if Enterprise's schema changes.
        template_field = next(name for name in ('product_template_id', 'product_tmpl_id') if name in Pricing._fields)
        amount_field = next(name for name in ('price', 'fixed_price') if name in Pricing._fields)
        Pricing.create({template_field: product.product_tmpl_id.id, 'plan_id': plan.id, amount_field: amount})
        return product

    def _quote(self, product, plan, flow='new', source=False, start='2026-09-15', months=False):
        return self.Pos.wgs_get_subscription_pricing_for_pos(
            partner_id=self.holder.id, product_id=product.id, flow=flow,
            source_subscription_id=source.id if source else False,
            preferred_plan_id=plan.id, start_date=start,
            domiciliation_installment_sequences=months,
        )

    def _paid(self, product, plan, flow='new', source=False, participants=False, start='2026-09-15', months=False):
        quote = self._quote(product, plan, flow, source, start, months)
        config = {
            'line_uuid': str(uuid4()), 'product_id': product.id, 'quantity': 1,
            'flow': flow, 'partner_id': self.holder.id,
            'source_subscription_id': source.id if source else False,
            'plan_id': quote['plan_id'], 'pricing_id': quote.get('pricing_id'),
            'participant_ids': participants or self.holder.ids,
            'pricing_snapshot': quote, 'pricing_lock': {'price_unit': quote['ticket_charge_now'], 'discount': 0},
        }
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
                       'price_unit': quote['ticket_charge_now'], 'discount': 0}],
        })
        order._wgs_apply_subscription_line_configs([config])
        order.write({'state': 'paid'})
        order._wgs_sync_subscription_sales()
        return order, order.lines.wgs_sale_order_id

    def test_paid_new_has_one_application_and_exact_month(self):
        order, subscription = self._paid(self.solo, self.month)
        self.assertEqual(subscription.plan_id, self.month)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-14'))
        self.assertEqual(order.lines.wgs_application_state, 'applied')
        receipt = order.lines.wgs_application_receipt
        order._wgs_sync_subscription_sales()
        self.assertEqual(order.lines.wgs_application_receipt, receipt)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-14'))

    def test_replay_after_closure_does_not_reactivate_or_extend(self):
        order, subscription = self._paid(self.solo, self.month)
        subscription.write({'subscription_state': '6_churn'})
        order._wgs_sync_subscription_sales()
        self.assertEqual(subscription.subscription_state, '6_churn')
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-14'))

    def test_holder_is_not_inferred_from_participant_order(self):
        self.holder, self.member = self.member, self.holder
        self.assertLess(self.member.id, self.holder.id)
        order, subscription = self._paid(
            self.pair, self.month, participants=[self.member.id, self.holder.id],
        )
        self.assertEqual(order.partner_id, self.holder)
        self.assertEqual(subscription.partner_id, self.holder)
        self.assertEqual(set(subscription.participant_ids.ids), set((self.holder | self.member).ids))

    def test_payment_preflight_accepts_identical_retry_after_lost_response(self):
        order, subscription = self._paid(self.solo, self.month)
        config = json.loads(order.lines.wgs_operation_config_json)
        result = self.Pos.wgs_stage_subscription_config_for_uuid(order.uuid, [config], {
            'partner_id': self.holder.id, 'company_id': order.company_id.id,
        })
        self.assertTrue(result['already_applied'])
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-14'))
        config['discount_percent'] = 10
        with self.assertRaises(UserError):
            self.Pos.wgs_stage_subscription_config_for_uuid(order.uuid, [config], {
                'partner_id': self.holder.id, 'company_id': order.company_id.id,
            })

    def test_daily_to_monthly_reenrollment_replaces_plan_and_period(self):
        _order, subscription = self._paid(self.daily, self.day)
        subscription.write({'subscription_state': '6_churn'})
        order, result = self._paid(self.solo, self.month, 'reenroll', subscription)
        self.assertEqual(result, subscription)
        self.assertEqual(result.plan_id, self.month)
        self.assertEqual(result.end_date, fields.Date.to_date('2026-10-14'))
        self.assertEqual(result._get_recurring_lines().product_id, self.solo)
        order._wgs_sync_subscription_sales()
        self.assertEqual(result.end_date, fields.Date.to_date('2026-10-14'))

    def test_future_package_and_participants_wait_until_paid_period_ends(self):
        _order, subscription = self._paid(self.solo, self.month)
        renewal, _subscription = self._paid(
            self.pair, self.month, 'renewal', subscription, (self.holder | self.member).ids,
        )
        self.assertEqual(renewal.lines.wgs_application_state, 'scheduled')
        self.assertEqual(subscription._get_recurring_lines().product_id, self.solo)
        self.assertNotIn(self.member, subscription.participant_ids)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-10-14'))
        self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(renewal.lines.wgs_application_state, 'scheduled')
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 15, 12)):
            self.Pos._wgs_apply_due_package_changes()
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(renewal.lines.wgs_application_state, 'applied')
        self.assertEqual(subscription._get_recurring_lines().product_id, self.pair)
        self.assertIn(self.member, subscription.participant_ids)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-11-14'))

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
        self.assertEqual(second.lines.wgs_application_date, fields.Date.to_date('2026-11-15'))
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 15, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(first.lines.wgs_application_state, 'applied')
        self.assertEqual(second.lines.wgs_application_state, 'scheduled')
        self.assertIn(self.member, subscription.participant_ids)
        self.assertNotIn(second_member, subscription.participant_ids)
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 11, 15, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(second.lines.wgs_application_state, 'applied')
        self.assertIn(second_member, subscription.participant_ids)
        self.assertNotIn(self.member, subscription.participant_ids)
        self.assertEqual(subscription.end_date, fields.Date.to_date('2026-12-14'))

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

    def test_domiciliation_restart_preserves_previous_installments(self):
        self.month.write({'wgs_domiciliation_enabled': True, 'wgs_domiciliation_term_months': 12})
        _order, subscription = self._paid(self.solo, self.month, start='2026-02-15', months=[1, 12])
        old = subscription.wgs_domiciliation_contract_id
        old_ids = old.installment_ids.ids
        paid_ids = old.installment_ids.filtered(lambda item: item.state == 'paid').ids
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
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 10, 15, 12)):
            self.Pos._wgs_apply_due_package_changes()
        self.assertEqual(order.lines.wgs_application_state, 'applied')
        contract = subscription.wgs_domiciliation_contract_id
        self.assertEqual(contract.state, 'active')
        self.assertEqual(contract.installment_ids.filtered(lambda item: item.state == 'paid').mapped('sequence'), [1, 2])
