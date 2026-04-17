from odoo import Command, fields
from odoo.tests.common import TransactionCase


class TestPosSubscriptionPricing(TransactionCase):
    def setUp(self):
        super().setUp()
        self.PosOrder = self.env['pos.order']
        self.tax_16 = self.env['account.tax'].create(
            {
                'name': 'IVA 16 POS',
                'amount': 16.0,
                'amount_type': 'percent',
                'type_tax_use': 'sale',
                'price_include': False,
                'company_id': self.env.company.id,
            }
        )
        self.partner = self.env['res.partner'].create({'name': 'Cliente POS'})
        self.product = self.env['product.product'].create(
            {
                'name': 'Plan POS',
                'detailed_type': 'service',
                'list_price': 100.0,
                'sale_ok': True,
                'available_in_pos': True,
                'recurring_invoice': True,
                'taxes_id': [(6, 0, [self.tax_16.id])],
            }
        )
        self.plan = self.env['sale.subscription.plan'].create(
            {
                'name': 'Plan Mensual POS',
                'recurring_interval': 1,
                'recurring_rule_type': 'month',
            }
        )

    def _create_subscription_like_order(self, *, name='SO TEST', start_date='2026-03-26'):
        order = self.env['sale.order'].create(
            {
                'partner_id': self.partner.id,
                'order_line': [
                    Command.create(
                        {
                            'name': self.product.display_name,
                            'product_id': self.product.id,
                            'product_uom_qty': 1,
                            'price_unit': 100.0,
                        }
                    )
                ],
            }
        )
        order_line = order.order_line[:1]
        line_fields = order_line._fields
        line_updates = {}
        for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
            if field_name in line_fields:
                line_updates[field_name] = self.plan.id
        if line_updates:
            order_line.write(line_updates)

        order_updates = {}
        for field_name in ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date'):
            if field_name in order._fields:
                order_updates[field_name] = start_date
                break
        for field_name in ('subscription_state',):
            if field_name in order._fields:
                order_updates[field_name] = 'progress'
        for field_name in ('recurring_next_date', 'next_invoice_date'):
            if field_name in order._fields:
                order_updates[field_name] = '2026-04-26'
                break
        for field_name in ('end_date', 'date_end', 'subscription_end_date', 'recurring_end_date'):
            if field_name in order._fields:
                order_updates[field_name] = '2026-04-25'
                break
        if order_updates:
            order.write(order_updates)
        return order

    def test_price_with_taxes_for_pos_uses_product_taxes(self):
        total = self.PosOrder._wgs_get_price_with_taxes_for_pos(self.product, 100.0, partner=self.partner)
        self.assertEqual(total, 116.0)

    def test_subscription_charge_for_pos_returns_tax_included_display_price(self):
        charge = self.PosOrder.sudo().wgs_get_subscription_charge_for_pos(
            self.partner.id,
            self.product.id,
            fallback=100.0,
            preferred_plan_id=False,
            preferred_pricing_id=False,
        )
        self.assertEqual(charge['recurring_price'], 100.0)
        self.assertEqual(charge['display_recurring_price'], 116.0)

    def test_product_context_plans_expose_display_price_with_taxes(self):
        context = self.PosOrder.sudo().wgs_get_subscription_product_context_for_pos(
            self.product.id,
            fallback=100.0,
        )
        self.assertEqual(context['default_price'], 100.0)
        self.assertEqual(context['default_display_price'], 116.0)

    def test_plan_period_end_date_is_inclusive(self):
        start_date = fields.Date.to_date('2026-03-26')
        period_end = self.PosOrder._wgs_get_plan_period_end_date(self.plan, start_date)
        self.assertEqual(period_end, fields.Date.to_date('2026-04-25'))

    def test_plan_period_end_date_supports_daily_plans(self):
        daily_plan = self.env['sale.subscription.plan'].create(
            {
                'name': 'Plan Diario POS',
                'recurring_interval': 1,
                'recurring_rule_type': 'week',
                'wgs_single_day_plan': True,
            }
        )

        start_date = fields.Date.to_date('2026-03-26')
        period_end = self.PosOrder._wgs_get_plan_period_end_date(daily_plan, start_date)
        threshold = self.PosOrder._wgs_get_plan_min_end_threshold(daily_plan, start_date)

        self.assertEqual(threshold, fields.Date.to_date('2026-03-27'))
        self.assertEqual(period_end, fields.Date.to_date('2026-03-26'))

    def test_close_source_subscription_after_upgrade_sets_previous_day_end(self):
        order = self._create_subscription_like_order()
        end_field = self.PosOrder._wgs_find_subscription_end_date_field(order)
        self.assertTrue(end_field)

        self.PosOrder._wgs_close_source_subscription_after_upgrade(order, '2026-04-26')

        self.assertEqual(
            fields.Date.to_date(order[end_field]),
            fields.Date.to_date('2026-04-25'),
        )

    def test_upsale_schedule_keeps_source_renewal_anchor(self):
        order = self._create_subscription_like_order()

        schedule = self.PosOrder._wgs_get_upsale_schedule_from_source(
            order,
            today='2026-04-10',
        )

        self.assertEqual(
            fields.Date.to_date(schedule['sale_start_date']),
            fields.Date.to_date('2026-04-10'),
        )
        self.assertEqual(
            fields.Date.to_date(schedule['subscription_end_date']),
            fields.Date.to_date('2026-04-25'),
        )
        self.assertEqual(
            fields.Date.to_date(schedule['next_billing_date']),
            fields.Date.to_date('2026-04-26'),
        )

    def test_reenroll_charge_allows_closed_subscription(self):
        order = self._create_subscription_like_order()
        if 'subscription_state' in order._fields:
            order.write({'subscription_state': 'closed'})

        charge = self.PosOrder.sudo().wgs_get_subscription_reenroll_charge_for_pos(
            order.id,
            self.product.id,
            preferred_plan_id=False,
            preferred_pricing_id=False,
        )

        self.assertEqual(charge['recurring_price'], 100.0)
        self.assertEqual(charge['display_recurring_price'], 116.0)
        self.assertTrue(charge['is_reenroll'])
