"""Query budgets protect the directory without caching commercial state."""

from datetime import date
from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestDirectoryPerformance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Order = cls.env['sale.order']
        cls.site = cls.env['access_control.site'].create({
            'name': 'Directory query budget', 'code': 'DIRECTORY-PERF',
            'company_id': cls.env.company.id,
        })
        cls.plan = cls.env['sale.subscription.plan'].create({
            'name': 'Directory monthly', 'billing_period_value': 1, 'billing_period_unit': 'month',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Directory subscription', 'default_code': 'DIR-QA',
            'type': 'service', 'recurring_invoice': True,
            'company_id': cls.env.company.id,
            'wgs_access_site_ids': [Command.set(cls.site.ids)],
        })
        cls.partners = cls.env['res.partner'].create([
            {'name': 'Directory budget %03d' % index, 'company_id': cls.env.company.id}
            for index in range(100)
        ])
        cls.orders = cls.Order.create([{
            'partner_id': partner.id, 'plan_id': cls.plan.id,
            'state': 'sale', 'subscription_state': '3_progress',
            'start_date': '2026-11-01', 'next_invoice_date': '2026-12-02',
            'end_date': '2026-12-01', 'wgs_access_site_ids': [Command.set(cls.site.ids)],
            'order_line': [Command.create({
                'product_id': cls.product.id, 'name': 'Historical membership',
                'product_uom_qty': 1, 'price_unit': 100,
            })],
        } for partner in cls.partners])

    def _measure(self, callback):
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        result = callback()
        return result, self.env.cr.sql_log_count - before

    def test_site_lookup_is_once_per_subscription_batch(self):
        original = type(self.Order)._wgs_get_pos_access_sites_for_pos
        with patch.object(type(self.Order), '_wgs_get_pos_access_sites_for_pos', autospec=True,
                          side_effect=original) as lookup:
            selected = self.Order._filter_local_pos_subscriptions_for_pos(self.orders)
        self.assertEqual(selected, self.orders)
        self.assertEqual(lookup.call_count, 1)

    def test_pos_history_and_replacement_relations_have_physical_indexes(self):
        columns = {'wgs_sale_order_id', 'wgs_subscription_source_id'}
        for name in columns:
            self.assertEqual(self.env['pos.order.line']._fields[name].index, 'btree_not_null')
        self.env.cr.execute("""
            SELECT attribute.attname
            FROM pg_index AS idx
            JOIN pg_attribute AS attribute
              ON attribute.attrelid = idx.indrelid
             AND attribute.attnum = ANY(idx.indkey)
            WHERE idx.indrelid = 'pos_order_line'::regclass
              AND idx.indisvalid AND idx.indisready
              AND idx.indnkeyatts = 1
              AND attribute.attname IN %s
        """, [tuple(sorted(columns))])
        self.assertEqual({row[0] for row in self.env.cr.fetchall()}, columns)

    def test_directory_summary_has_a_constant_query_budget(self):
        with patch.object(type(self.Order), '_wgs_subscription_business_today_for_pos', return_value=date(2026, 11, 4)):
            counts, queries = self._measure(lambda: self.Order.get_partner_directory_summary_for_pos({
                'company_id': self.env.company.id,
            }))
        self.assertGreaterEqual(counts['progress'], 100)
        self.assertLess(queries, 90, 'Directory summary regressed to per-contract SQL: %s' % queries)

    def test_filtered_page_has_a_bounded_query_budget(self):
        with patch.object(type(self.Order), '_wgs_subscription_business_today_for_pos', return_value=date(2026, 11, 4)):
            rows, queries = self._measure(lambda: self.Order.get_partner_directory_rows_for_pos(
                0, 51, 'actionable', False, self.env.company.id,
            ))
        self.assertEqual(len(rows), 51)
        self.assertLess(queries, 150, 'Filtered page regressed to per-contract SQL: %s' % queries)

    def test_contact_search_does_not_classify_unrelated_subscriptions(self):
        original = type(self.Order)._filter_local_pos_subscriptions_for_pos
        batches = []

        def record_batch(orders, candidates, **kwargs):
            batches.append(candidates.ids)
            return original(orders, candidates, **kwargs)

        with patch.object(type(self.Order), '_filter_local_pos_subscriptions_for_pos', record_batch):
            ids = self.Order._get_partner_ids_matching_directory_search_for_pos('Directory budget 000')
        self.assertIn(self.partners[0].id, ids)
        self.assertTrue(all(not batch for batch in batches), batches)

    def test_product_search_preserves_code_display_name_and_archived_history(self):
        self.product.active = False
        for search in ('DIR-QA', '[DIR-QA] Directory subscription', 'directory subscription', 'Historical membership'):
            with self.subTest(search=search):
                ids = self.Order._get_partner_ids_matching_directory_search_for_pos(search)
                self.assertTrue(set(self.partners.ids).issubset(ids))

    def test_nonrecurring_line_name_does_not_match_subscription_package_search(self):
        retail = self.env['product.product'].create({'name': 'Retail unique needle'})
        self.orders[0].write({'order_line': [Command.create({
            'product_id': retail.id, 'name': retail.name, 'product_uom_qty': 1, 'price_unit': 5,
        })]})
        ids = self.Order._get_partner_ids_matching_directory_search_for_pos('Retail unique needle')
        self.assertNotIn(self.partners[0].id, ids)

    def test_block_storage_is_batched_and_preserves_each_partners_flags(self):
        blocked = self.partners[0]
        blocked.write({
            'wgs_access_blocked': True, 'wgs_access_block_reason': 'Directory QA block',
        })
        self.env['ir.config_parameter'].sudo().set_param(
            self.partners[1]._wgs_access_block_param_key(self.partners[1].id, 'blocked_by_id'),
            'invalid legacy id',
        )
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        flags = [(p.wgs_access_blocked, p.wgs_access_block_reason, p.wgs_access_blocked_by_id.id)
                 for p in self.partners]
        queries = self.env.cr.sql_log_count - before
        self.assertTrue(flags[0][0])
        self.assertEqual(flags[0][1], 'Directory QA block')
        self.assertTrue(all(not flag[0] for flag in flags[1:]))
        self.assertFalse(flags[1][2])
        self.assertLess(queries, 8, 'Block flags regressed to per-partner SQL: %s' % queries)
