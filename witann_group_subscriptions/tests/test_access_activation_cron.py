from datetime import date, timedelta
from unittest.mock import patch

from odoo.fields import Command
from odoo.tests.common import TransactionCase


class TestAccessActivationCron(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Order = self.env['sale.order']
        self.Person = self.env['access_control.person'].with_context(active_test=False)
        self.today = date(2026, 9, 14)
        clock = patch.object(type(self.Order), '_wgs_get_subscription_business_today', return_value=self.today)
        self.business_clock = clock.start()
        self.addCleanup(clock.stop)
        self.site = self.env['access_control.site'].create({
            'name': 'Activation test', 'code': 'WGS-ACTIVATION', 'company_id': self.env.company.id,
        })
        self.plan = self.env['sale.subscription.plan'].create({
            'name': 'Monthly activation', 'billing_period_value': 1, 'billing_period_unit': 'month',
        })
        self.product = self.env['product.product'].create({
            'name': 'Pair activation', 'type': 'service', 'recurring_invoice': True,
            'max_participants_total': 2, 'list_price': 100,
            'wgs_access_site_ids': [Command.set(self.site.ids)],
        })

    def _create_future_pair(self):
        partners = self.env['res.partner'].create([{'name': 'Activation owner'}, {'name': 'Activation member'}])
        start = self.today + timedelta(days=1)
        order = self.Order.create({
            'partner_id': partners[0].id,
            'participant_ids': [Command.set(partners.ids)],
            'company_id': self.env.company.id,
            'plan_id': self.plan.id,
            'state': 'sale',
            'subscription_state': '3_progress',
            'start_date': start,
            'wgs_effective_start_date': start,
            'end_date': start + timedelta(days=29),
            'next_invoice_date': start + timedelta(days=30),
            'order_line': [Command.create({
                'product_id': self.product.id, 'name': self.product.name,
                'product_uom_qty': 1, 'price_unit': 100,
            })],
        })
        self.assertFalse(self.Person.search([('partner_id', 'in', partners.ids)]))
        return order, partners

    def _pending_orders(self, orders):
        return self.Order.search(
            self.Order._wgs_get_pending_access_activation_domain(self.business_clock.return_value)
            & [('id', 'in', orders.ids)]
        )

    def test_cron_activates_due_pair_outside_historical_page_and_is_idempotent(self):
        order, partners = self._create_future_pair()
        self.assertFalse(self._pending_orders(order))
        self.business_clock.return_value = self.today + timedelta(days=1)
        self.assertEqual(self._pending_orders(order), order)

        # The historical page deliberately contains neither member of the pair.
        page = {'partner_ids': [], 'order_count': 0, 'next_order_after_id': 10, 'next_person_after_id': 20}
        with patch.object(type(self.Order), '_wgs_get_subscription_access_audit_partner_ids', return_value=page):
            result = self.Order._cron_wgs_sync_subscription_access_control(batch_limit=1)
            people = self.Person.search([('partner_id', 'in', partners.ids)])
            self.assertEqual(len(people), 2)
            self.assertTrue(all(p.active and p.access_state == 'enabled' and p.global_user_id for p in people))
            self.assertTrue(all(p.site_ids == self.site for p in people))
            self.assertEqual(set(result['pending_activation']['repaired_partner_ids']), set(partners.ids))
            self.assertEqual(result['post_sync_issues'], 0)
            self.assertFalse(self._pending_orders(order))

            Change = self.env['access_control.sync_change']
            changes = Change.search([('person_id', 'in', people.ids)])
            self.assertTrue(changes)
            self.assertTrue(all(changes.mapped('priority')))
            second_result = self.Order._cron_wgs_sync_subscription_access_control(batch_limit=1)
            self.assertEqual(second_result['pending_activation']['repaired'], 0)
            self.assertEqual(Change.search([('person_id', 'in', people.ids)]), changes)

    def test_pending_search_respects_blocks_expiry_and_future_starts(self):
        order, partners = self._create_future_pair()
        other_order, _partners = self._create_future_pair()
        self.business_clock.return_value = self.today + timedelta(days=1)
        partners.write({'wgs_access_blocked': True, 'wgs_access_block_reason': 'Test block'})
        self.assertFalse(self._pending_orders(order))
        self.assertEqual(self._pending_orders(other_order), other_order)
        other_order.with_context(wgs_defer_access_sync=True).write({'subscription_state': '6_churn'})
        self.assertFalse(self._pending_orders(other_order))
        other_order.with_context(wgs_defer_access_sync=True).write({
            'subscription_state': '3_progress', 'end_date': self.today, 'next_invoice_date': self.today,
        })
        self.assertFalse(self._pending_orders(other_order))

    def test_cron_bounds_activation_batch_and_reuses_archived_person(self):
        first, _first_partners = self._create_future_pair()
        second, second_partners = self._create_future_pair()
        archived = self.Person.create({
            'partner_id': second_partners[1].id, 'active': False, 'access_state': 'suspended',
            'site_ids': [Command.set(self.site.ids)], 'managed_by_subscription': True,
        })
        self.business_clock.return_value = self.today + timedelta(days=1)
        page = {'partner_ids': [], 'order_count': 0, 'next_order_after_id': 10, 'next_person_after_id': 20}
        with patch.object(type(self.Order), '_wgs_get_subscription_access_audit_partner_ids', return_value=page):
            self.Order._cron_wgs_sync_subscription_access_control(batch_limit=1)
            self.assertFalse(self._pending_orders(first))
            self.assertEqual(self._pending_orders(second), second)
            self.Order._cron_wgs_sync_subscription_access_control(batch_limit=1)
        self.assertFalse(self._pending_orders(first | second))
        self.assertEqual(self.Person.search([('partner_id', '=', second_partners[1].id)]), archived)
        self.assertTrue(archived.active)
