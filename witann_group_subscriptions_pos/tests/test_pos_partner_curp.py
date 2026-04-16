from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestPosPartnerCurp(TransactionCase):
    def setUp(self):
        super().setUp()
        self.PosOrder = self.env['pos.order']
        self.Partner = self.env['res.partner']
        self.curp_field = 'x_studio_curp'
        if self.curp_field not in self.Partner._fields:
            self.skipTest('x_studio_curp no existe en este runtime.')

        self.product = self.env['product.product'].create(
            {
                'name': 'Plan CURP POS',
                'detailed_type': 'service',
                'list_price': 100.0,
                'sale_ok': True,
                'available_in_pos': True,
                'recurring_invoice': True,
                'wgs_requires_curp': True,
            }
        )

    def test_create_partner_for_pos_accepts_curp(self):
        result = self.PosOrder.sudo().wgs_create_partner_for_pos(
            {
                'name': 'Cliente POS CURP',
                'curp': 'abcd-010101-hdfrrn09',
            }
        )

        partner = self.Partner.browse(result['partner_id'])
        self.assertEqual(partner[self.curp_field], 'ABCD010101HDFRRN09')

    def test_update_partner_curp_for_pos_normalizes_value(self):
        partner = self.Partner.create({'name': 'Cliente update CURP'})

        result = self.PosOrder.sudo().wgs_update_partner_curp_for_pos(
            partner.id,
            'mopl-900101-mdfabc01',
        )

        partner.invalidate_recordset([self.curp_field])
        self.assertEqual(result['curp'], 'MOPL900101MDFABC01')
        self.assertEqual(partner[self.curp_field], 'MOPL900101MDFABC01')

    def test_update_partner_curp_for_pos_rejects_duplicates(self):
        self.Partner.create(
            {
                'name': 'Cliente base',
                self.curp_field: 'ABCD010101HDFRRN09',
            }
        )
        partner = self.Partner.create({'name': 'Cliente duplicado'})

        with self.assertRaises(ValidationError):
            self.PosOrder.sudo().wgs_update_partner_curp_for_pos(
                partner.id,
                'abcd 010101 hdfrrn09',
            )

    def test_product_catalog_exposes_curp_requirement(self):
        catalog = self.PosOrder.sudo().wgs_get_subscription_product_catalog_for_pos(limit=20)
        item = next((row for row in catalog if row['id'] == self.product.id), None)

        self.assertTrue(item)
        self.assertTrue(item['requires_curp'])
