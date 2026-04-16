from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestResPartnerCurp(TransactionCase):
    def test_create_normalizes_curp(self):
        partner = self.env['res.partner'].create(
            {
                'name': 'Cliente CURP',
                'wgs_curp': ' abcd-010101-hdfrrn09 ',
            }
        )

        self.assertEqual(partner.wgs_curp, 'ABCD010101HDFRRN09')

    def test_duplicate_curp_is_rejected(self):
        self.env['res.partner'].create(
            {
                'name': 'Cliente 1',
                'wgs_curp': 'ABCD010101HDFRRN09',
            }
        )

        with self.assertRaises(ValidationError):
            self.env['res.partner'].create(
                {
                    'name': 'Cliente 2',
                    'wgs_curp': 'abcd 010101 hdfrrn09',
                }
            )

    def test_empty_curp_remains_optional(self):
        partner_a = self.env['res.partner'].create({'name': 'Sin CURP 1'})
        partner_b = self.env['res.partner'].create({'name': 'Sin CURP 2', 'wgs_curp': ''})

        self.assertFalse(partner_a.wgs_curp)
        self.assertFalse(partner_b.wgs_curp)

    def test_write_normalizes_curp(self):
        partner = self.env['res.partner'].create({'name': 'Cliente write'})

        partner.write({'wgs_curp': 'mopl-900101-mdfabc01'})

        self.assertEqual(partner.wgs_curp, 'MOPL900101MDFABC01')
