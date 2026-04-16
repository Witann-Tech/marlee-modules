from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestResPartnerCurp(TransactionCase):
    def setUp(self):
        super().setUp()
        self.curp_field = 'x_studio_curp'
        if self.curp_field not in self.env['res.partner']._fields:
            self.skipTest('x_studio_curp no existe en este runtime.')

    def test_create_accepts_curp_and_normalizes_it(self):
        partner = self.env['res.partner'].create(
            {
                'name': 'Cliente CURP',
                self.curp_field: ' abcd-010101-hdfrrn09 ',
            }
        )

        self.assertEqual(partner[self.curp_field], 'ABCD010101HDFRRN09')

    def test_duplicate_curp_is_rejected(self):
        self.env['res.partner'].create(
            {
                'name': 'Cliente 1',
                self.curp_field: 'ABCD010101HDFRRN09',
            }
        )

        with self.assertRaises(ValidationError):
            self.env['res.partner'].create(
                {
                    'name': 'Cliente 2',
                    self.curp_field: 'abcd 010101 hdfrrn09',
                }
            )

    def test_empty_curp_remains_optional(self):
        partner_a = self.env['res.partner'].create({'name': 'Sin CURP 1'})
        partner_b = self.env['res.partner'].create({'name': 'Sin CURP 2', self.curp_field: ''})

        self.assertFalse(partner_a[self.curp_field])
        self.assertFalse(partner_b[self.curp_field])

    def test_write_normalizes_curp(self):
        partner = self.env['res.partner'].create({'name': 'Cliente write'})

        partner.write({self.curp_field: 'mopl-900101-mdfabc01'})

        self.assertEqual(partner[self.curp_field], 'MOPL900101MDFABC01')
