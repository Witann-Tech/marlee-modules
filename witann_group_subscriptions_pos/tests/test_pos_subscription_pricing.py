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

    def test_subscription_pricing_for_pos_returns_tax_included_display_price(self):
        charge = self.PosOrder.sudo().wgs_get_subscription_pricing_for_pos(
            partner_id=self.partner.id,
            product_id=self.product.id,
            flow='new',
            source_subscription_id=False,
            pending_move_id=False,
            fallback=100.0,
            preferred_plan_id=False,
            preferred_pricing_id=False,
        )
        self.assertEqual(charge['recurring_price'], 100.0)
        self.assertEqual(charge['display_recurring_price'], 116.0)

    def test_subscription_catalog_is_structural_only(self):
        catalog = self.PosOrder.sudo().wgs_get_subscription_product_catalog_for_pos(limit=20)
        item = next((row for row in catalog if row['id'] == self.product.id), None)
        self.assertTrue(item)
        self.assertEqual(item['default_price'], 0.0)
        self.assertEqual(item['default_display_price'], 0.0)
        self.assertEqual(item['plans'], [])

    def test_subscription_catalog_includes_recurring_products_hidden_from_normal_pos_grid(self):
        hidden_product = self.env['product.product'].create(
            {
                'name': 'Plan oculto en grid POS',
                'detailed_type': 'service',
                'list_price': 150.0,
                'sale_ok': True,
                'available_in_pos': False,
                'recurring_invoice': True,
            }
        )
        catalog = self.PosOrder.sudo().wgs_get_subscription_product_catalog_for_pos(limit=50)
        item = next((row for row in catalog if row['id'] == hidden_product.id), None)
        self.assertTrue(item)

    def test_subscription_pricing_payload_exposes_display_price_with_taxes(self):
        payload = self.PosOrder.sudo().wgs_get_subscription_pricing_for_pos(
            partner_id=self.partner.id,
            product_id=self.product.id,
            flow='new',
            source_subscription_id=False,
            pending_move_id=False,
            fallback=100.0,
            preferred_plan_id=False,
            preferred_pricing_id=False,
        )
        self.assertEqual(payload['default_price'], 100.0)
        self.assertEqual(payload['default_display_price'], 116.0)

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

    def test_aligned_monthly_first_period_schedule_is_calendar_based(self):
        schedule = self.PosOrder._wgs_get_aligned_monthly_first_period_schedule('2026-05-12')

        self.assertEqual(schedule['subscription_start_date'], fields.Date.to_date('2026-05-01'))
        self.assertEqual(schedule['access_start_date'], fields.Date.to_date('2026-05-12'))
        self.assertEqual(schedule['subscription_end_date'], fields.Date.to_date('2026-05-31'))
        self.assertEqual(schedule['next_billing_date'], fields.Date.to_date('2026-06-01'))
        self.assertEqual(schedule['period_days'], 31)
        self.assertEqual(schedule['charge_days'], 20)

    def test_aligned_monthly_plan_charges_first_period_proportionally(self):
        alignment_field = self.PosOrder._wgs_get_period_alignment_field_name(self.plan)
        if not alignment_field:
            self.skipTest('El runtime no expone el campo nativo de alineación de periodo.')
        if 'sale.subscription.pricing' not in self.env.registry:
            self.skipTest('sale.subscription.pricing no existe en este runtime.')

        self.plan.write({alignment_field: True})

        pricing_model = self.env['sale.subscription.pricing']
        pricing_vals = {}
        for field_name in ('product_tmpl_id', 'product_template_id'):
            if field_name in pricing_model._fields:
                pricing_vals[field_name] = self.product.product_tmpl_id.id
                break
        for field_name in ('plan_id', 'subscription_plan_id', 'recurring_plan_id'):
            if field_name in pricing_model._fields:
                pricing_vals[field_name] = self.plan.id
                break
        for field_name in ('fixed_price', 'price', 'recurring_price', 'price_unit', 'list_price', 'amount'):
            if field_name in pricing_model._fields:
                pricing_vals[field_name] = 100.0
                break
        if 'name' in pricing_model._fields:
            pricing_vals['name'] = 'Pricing mensual alineado POS'

        try:
            pricing_model.create(pricing_vals)
        except Exception:
            self.skipTest('No se pudo crear sale.subscription.pricing alineado en este runtime.')

        charge = self.PosOrder.sudo().wgs_get_subscription_pricing_for_pos(
            partner_id=self.partner.id,
            product_id=self.product.id,
            flow='new',
            source_subscription_id=False,
            pending_move_id=False,
            fallback=100.0,
            preferred_plan_id=self.plan.id,
            preferred_pricing_id=False,
            start_date='2026-05-12',
        )

        self.assertEqual(charge['recurring_price'], 100.0)
        self.assertEqual(charge['charge_now'], 64.52)
        self.assertEqual(charge['display_charge_now'], 74.84)
        self.assertEqual(charge['ticket_charge_now'], 64.52)
        self.assertEqual(charge['ticket_recurring_price'], 100.0)
        self.assertEqual(charge['subscription_start_date'], '2026-05-01')
        self.assertEqual(charge['first_period_access_start_date'], '2026-05-12')
        self.assertEqual(charge['subscription_end_date'], '2026-05-31')
        self.assertEqual(charge['next_billing_date'], '2026-06-01')
        self.assertTrue(charge['first_period_alignment'])
        self.assertEqual(charge['first_period_days'], 31)
        self.assertEqual(charge['first_period_charge_days'], 20)

    def test_subscription_pricing_beats_generic_pricelist_candidate(self):
        pricing_model_name = 'sale.subscription.pricing'
        if pricing_model_name not in self.env.registry:
            self.skipTest('sale.subscription.pricing no existe en este runtime.')

        self.product.write({'list_price': 90.0})

        pricelist_item_model = self.env['product.pricelist.item']
        pricelist_item_vals = {'fixed_price': 90.0}
        if 'product_tmpl_id' in pricelist_item_model._fields:
            pricelist_item_vals['product_tmpl_id'] = self.product.product_tmpl_id.id
        elif 'product_template_id' in pricelist_item_model._fields:
            pricelist_item_vals['product_template_id'] = self.product.product_tmpl_id.id
        if 'compute_price' in pricelist_item_model._fields:
            pricelist_item_vals['compute_price'] = 'fixed'
        pricelist_item_model.create(pricelist_item_vals)

        pricing_model = self.env[pricing_model_name]
        pricing_vals = {}
        for field_name in ('product_tmpl_id', 'product_template_id'):
            if field_name in pricing_model._fields:
                pricing_vals[field_name] = self.product.product_tmpl_id.id
                break
        for field_name in ('plan_id', 'subscription_plan_id', 'recurring_plan_id'):
            if field_name in pricing_model._fields:
                pricing_vals[field_name] = self.plan.id
                break
        for field_name in ('fixed_price', 'price', 'recurring_price', 'price_unit', 'list_price', 'amount'):
            if field_name in pricing_model._fields:
                pricing_vals[field_name] = 50.0
                break
        for field_name in ('name',):
            if field_name in pricing_model._fields and field_name not in pricing_vals:
                pricing_vals[field_name] = 'Pricing recurrente POS'

        try:
            pricing_model.create(pricing_vals)
        except Exception:
            self.skipTest('No se pudo crear sale.subscription.pricing en este runtime.')

        charge = self.PosOrder.sudo().wgs_get_subscription_pricing_for_pos(
            partner_id=self.partner.id,
            product_id=self.product.id,
            flow='new',
            source_subscription_id=False,
            pending_move_id=False,
            fallback=90.0,
            preferred_plan_id=self.plan.id,
            preferred_pricing_id=False,
        )

        self.assertEqual(charge['recurring_price'], 50.0)

    def test_pricing_payload_plan_list_prefers_subscription_pricing_over_generic_candidate(self):
        pricing_model_name = 'sale.subscription.pricing'
        if pricing_model_name not in self.env.registry:
            self.skipTest('sale.subscription.pricing no existe en este runtime.')

        self.product.write({'list_price': 90.0})

        pricelist_item_model = self.env['product.pricelist.item']
        pricelist_item_vals = {'fixed_price': 90.0}
        if 'product_tmpl_id' in pricelist_item_model._fields:
            pricelist_item_vals['product_tmpl_id'] = self.product.product_tmpl_id.id
        elif 'product_template_id' in pricelist_item_model._fields:
            pricelist_item_vals['product_template_id'] = self.product.product_tmpl_id.id
        if 'compute_price' in pricelist_item_model._fields:
            pricelist_item_vals['compute_price'] = 'fixed'
        pricelist_item_model.create(pricelist_item_vals)

        pricing_model = self.env[pricing_model_name]
        pricing_vals = {}
        for field_name in ('product_tmpl_id', 'product_template_id'):
            if field_name in pricing_model._fields:
                pricing_vals[field_name] = self.product.product_tmpl_id.id
                break
        for field_name in ('plan_id', 'subscription_plan_id', 'recurring_plan_id'):
            if field_name in pricing_model._fields:
                pricing_vals[field_name] = self.plan.id
                break
        for field_name in ('fixed_price', 'price', 'recurring_price', 'price_unit', 'list_price', 'amount'):
            if field_name in pricing_model._fields:
                pricing_vals[field_name] = 50.0
                break
        if 'name' in pricing_model._fields:
            pricing_vals['name'] = 'Pricing visible POS'

        try:
            pricing_model.create(pricing_vals)
        except Exception:
            self.skipTest('No se pudo crear sale.subscription.pricing en este runtime.')

        payload = self.PosOrder.sudo().wgs_get_subscription_pricing_for_pos(
            partner_id=self.partner.id,
            product_id=self.product.id,
            flow='new',
            source_subscription_id=False,
            pending_move_id=False,
            fallback=90.0,
            preferred_plan_id=False,
            preferred_pricing_id=False,
        )

        self.assertEqual(payload['default_price'], 50.0)
        self.assertEqual(len(payload['plans']), 1)
        self.assertEqual(payload['plans'][0]['price'], 50.0)

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

        charge = self.PosOrder.sudo().wgs_get_subscription_pricing_for_pos(
            partner_id=False,
            product_id=self.product.id,
            flow='reenroll',
            source_subscription_id=order.id,
            pending_move_id=False,
            fallback=0.0,
            preferred_plan_id=False,
            preferred_pricing_id=False,
        )

        self.assertEqual(charge['recurring_price'], 100.0)
        self.assertEqual(charge['display_recurring_price'], 116.0)
        self.assertTrue(charge['is_reenroll'])

    def test_reenroll_charge_allows_churned_subscription(self):
        order = self._create_subscription_like_order()
        if 'subscription_state' in order._fields:
            order.write({'subscription_state': 'churned'})

        charge = self.PosOrder.sudo().wgs_get_subscription_pricing_for_pos(
            partner_id=False,
            product_id=self.product.id,
            flow='reenroll',
            source_subscription_id=order.id,
            pending_move_id=False,
            fallback=0.0,
            preferred_plan_id=False,
            preferred_pricing_id=False,
        )

        self.assertEqual(charge['recurring_price'], 100.0)
        self.assertEqual(charge['display_recurring_price'], 116.0)
        self.assertTrue(charge['is_reenroll'])

    def test_reenroll_aligned_plan_charges_full_package_not_prorated(self):
        alignment_field = self.PosOrder._wgs_get_period_alignment_field_name(self.plan)
        if not alignment_field:
            self.skipTest('El runtime no expone el campo nativo de alineación de periodo.')
        self.plan.write({alignment_field: True})
        order = self._create_subscription_like_order()
        if 'subscription_state' in order._fields:
            order.write({'subscription_state': 'closed'})

        charge = self.PosOrder.sudo().wgs_get_subscription_pricing_for_pos(
            partner_id=False,
            product_id=self.product.id,
            flow='reenroll',
            source_subscription_id=order.id,
            pending_move_id=False,
            fallback=0.0,
            preferred_plan_id=self.plan.id,
            preferred_pricing_id=False,
            start_date='2026-05-12',
        )

        self.assertEqual(charge['recurring_price'], 100.0)
        self.assertEqual(charge['charge_now'], 100.0)
        self.assertEqual(charge['display_charge_now'], 116.0)
        self.assertEqual(charge['ticket_charge_now'], 100.0)
        self.assertFalse(charge['first_period_alignment'])
        self.assertFalse(charge['subscription_start_date'])
        self.assertFalse(charge['subscription_end_date'])
        self.assertTrue(charge['is_reenroll'])

    def test_reenroll_reactivation_resolves_progress_state(self):
        order = self._create_subscription_like_order()

        progress_state = self.PosOrder._wgs_find_subscription_progress_state_value(order)

        self.assertTrue(progress_state)
        if 'subscription_state' in order._fields:
            order.write({'subscription_state': 'closed'})
            self.PosOrder._wgs_reactivate_subscription_order_for_pos(order)
            self.assertEqual(order.subscription_state, progress_state)

    def test_reenroll_period_normalization_recomputes_invalid_same_day_end(self):
        end_date, next_billing_date, single_day = self.PosOrder._wgs_normalize_subscription_period_for_pos(
            product=self.product,
            plan_record=self.plan,
            subscription_start_date=fields.Date.to_date('2026-07-01'),
            subscription_end_date=fields.Date.to_date('2026-07-01'),
            next_billing_date=False,
        )

        self.assertFalse(single_day)
        self.assertEqual(end_date, fields.Date.to_date('2026-07-31'))
        self.assertEqual(next_billing_date, fields.Date.to_date('2026-08-01'))

    def test_reenroll_plan_fallback_does_not_inherit_source_plan_for_different_product(self):
        order = self._create_subscription_like_order()
        target_product = self.env['product.product'].create(
            {
                'name': 'Plan POS reinscripcion diferente',
                'detailed_type': 'service',
                'list_price': 150.0,
                'sale_ok': True,
                'available_in_pos': True,
                'recurring_invoice': True,
            }
        )

        inherited_plan_id = self.PosOrder._wgs_extract_plan_id_from_subscription_source_line(
            order,
            target_product,
        )

        self.assertFalse(inherited_plan_id)

    def test_reenroll_to_single_package_replaces_product_participants_and_access_snapshot(self):
        site_old = self.env['access_control.site'].create(
            {
                'name': 'Sitio paquete anterior',
                'code': 'OLD-POS',
                'company_id': self.env.company.id,
            }
        )
        site_new = self.env['access_control.site'].create(
            {
                'name': 'Sitio paquete destino',
                'code': 'NEW-POS',
                'company_id': self.env.company.id,
            }
        )
        participant_a = self.env['res.partner'].create({'name': 'Participante POS A'})
        participant_b = self.env['res.partner'].create({'name': 'Participante POS B'})
        self.product.product_tmpl_id.write({
            'max_participants_total': 3,
            'wgs_access_site_ids': [Command.set([site_old.id])],
        })
        target_product = self.env['product.product'].create(
            {
                'name': 'Plan POS individual destino',
                'detailed_type': 'service',
                'list_price': 120.0,
                'sale_ok': True,
                'available_in_pos': True,
                'recurring_invoice': True,
                'max_participants_total': 1,
            }
        )
        target_product.product_tmpl_id.write({'wgs_access_site_ids': [Command.set([site_new.id])]})

        order = self._create_subscription_like_order(start_date='2026-05-01')
        order.write({
            'participant_ids': [Command.set([self.partner.id, participant_a.id, participant_b.id])],
            'subscription_state': 'closed',
        })
        order._wgs_update_access_snapshot(force=True)
        self.assertEqual(set(order.wgs_access_site_ids.ids), {site_old.id})

        pos_line = self.env['pos.order.line'].new(
            {
                'product_id': target_product.id,
                'qty': 1,
                'price_unit': 120.0,
                'discount': 0.0,
                'wgs_participant_ids_json': '[]',
            }
        )
        participant_ids = self.PosOrder._wgs_resolve_subscription_participant_ids_for_pos_line(
            line=pos_line,
            holder_partner=order.partner_id,
            product=target_product,
            qty=1,
        )
        source_line = order._get_recurring_lines()[:1]
        new_line = self.PosOrder._wgs_apply_reenroll_source_line_values(
            source_order=order,
            source_line=source_line,
            pos_line=pos_line,
            product=target_product,
            qty=1,
            recurring_price_unit=120.0,
            recurring_plan_id=self.plan.id,
        )
        self.PosOrder._wgs_sync_subscription_metadata(
            sale_order=order,
            participant_ids=participant_ids,
            contract_date=fields.Date.to_date('2026-07-01'),
            subscription_start_date=fields.Date.to_date('2026-07-01'),
            subscription_end_date=fields.Date.to_date('2026-07-31'),
            next_billing_date=fields.Date.to_date('2026-08-01'),
        )
        self.PosOrder._wgs_reactivate_subscription_order_for_pos(order)
        self.PosOrder._wgs_finalize_reenroll_subscription_access_for_pos(
            order,
            extra_partner_ids={self.partner.id, participant_a.id, participant_b.id},
        )

        order.invalidate_recordset(['order_line', 'participant_ids', 'wgs_access_site_ids'])
        recurring_lines = order._get_recurring_lines()
        self.assertEqual(recurring_lines, new_line)
        self.assertEqual(order.participant_ids.ids, [self.partner.id])
        self.assertEqual(set(order.wgs_access_site_ids.ids), {site_new.id})

        item = order._build_pos_subscription_status_item(fields.Date.to_date('2026-07-15'))
        self.assertEqual(item['package_names'], [target_product.display_name])
        self.assertEqual(item['native_state_key'], 'progress')
        self.assertEqual(item['access_state'], 'enabled')

    def test_subscription_detail_prefers_active_card_over_renew_or_churned(self):
        items = [
            {
                'subscription_id': 1,
                'native_state_key': 'renew',
                'can_renew': True,
                '_wgs_creation_sort_key': ('2026-01-01 10:00:00', 1),
            },
            {
                'subscription_id': 2,
                'native_state_key': 'closed',
                'can_reenroll': True,
                '_wgs_creation_sort_key': ('2026-02-01 10:00:00', 2),
            },
            {
                'subscription_id': 3,
                'native_state_key': 'progress',
                'can_renew': True,
                '_wgs_creation_sort_key': ('2025-12-01 10:00:00', 3),
            },
        ]

        filtered = self.env['sale.order']._filter_partner_subscription_detail_items_for_pos(items)

        self.assertEqual([item['subscription_id'] for item in filtered], [3])
        self.assertFalse(any('_wgs_creation_sort_key' in item for item in filtered))

    def test_churned_subscription_is_not_marked_for_renewal_by_due_date(self):
        order = self._create_subscription_like_order()
        if 'subscription_state' not in order._fields:
            self.skipTest('subscription_state field is not available')
        order.write({'subscription_state': 'churned'})

        item = order._build_pos_subscription_status_item(fields.Date.to_date('2026-05-12'))

        self.assertEqual(item['native_state_key'], 'closed')
        self.assertFalse(item['is_valid'])
        self.assertFalse(item['can_renew'])
        self.assertTrue(item['can_reenroll'])

    def test_subscription_detail_keeps_latest_renew_when_no_active_card(self):
        items = [
            {
                'subscription_id': 1,
                'native_state_key': 'renew',
                'can_renew': True,
                '_wgs_creation_sort_key': ('2026-01-01 10:00:00', 1),
            },
            {
                'subscription_id': 2,
                'native_state_key': 'closed',
                'can_reenroll': True,
                '_wgs_creation_sort_key': ('2026-02-01 10:00:00', 2),
            },
            {
                'subscription_id': 4,
                'native_state_key': 'renew',
                'can_renew': True,
                '_wgs_creation_sort_key': ('2026-03-01 10:00:00', 4),
            },
        ]

        filtered = self.env['sale.order']._filter_partner_subscription_detail_items_for_pos(items)

        self.assertEqual([item['subscription_id'] for item in filtered], [4])
        self.assertFalse(any('_wgs_creation_sort_key' in item for item in filtered))
