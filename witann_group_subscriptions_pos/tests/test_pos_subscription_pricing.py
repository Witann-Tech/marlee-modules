from odoo.tests.common import TransactionCase


class TestPosSubscriptionPricing(TransactionCase):
    def setUp(self):
        super().setUp()
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

    def test_price_with_taxes_for_pos_uses_product_taxes(self):
        total = self.env['pos.order']._wgs_get_price_with_taxes_for_pos(self.product, 100.0, partner=self.partner)
        self.assertEqual(total, 116.0)

    def test_subscription_charge_for_pos_returns_tax_included_display_price(self):
        charge = self.env['pos.order'].sudo().wgs_get_subscription_charge_for_pos(
            self.partner.id,
            self.product.id,
            fallback=100.0,
            preferred_plan_id=False,
            preferred_pricing_id=False,
        )
        self.assertEqual(charge['recurring_price'], 100.0)
        self.assertEqual(charge['display_recurring_price'], 116.0)

    def test_product_context_plans_expose_display_price_with_taxes(self):
        context = self.env['pos.order'].sudo().wgs_get_subscription_product_context_for_pos(
            self.product.id,
            fallback=100.0,
        )
        self.assertEqual(context['default_price'], 100.0)
        self.assertEqual(context['default_display_price'], 116.0)
