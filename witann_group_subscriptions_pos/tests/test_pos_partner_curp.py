from odoo.tests.common import TransactionCase
from odoo import Command, fields


class TestPosPartnerCurp(TransactionCase):
    def setUp(self):
        super().setUp()
        self.PosOrder = self.env['pos.order']
        self.Partner = self.env['res.partner']
        self.Employee = self.env['hr.employee']
        self.curp_field = 'x_studio_curp'
        self.birthday_field = next(
            (
                field_name
                for field_name in (
                    'x_studio_fecha_de_nacimiento',
                    'birthday',
                    'birthdate_date',
                    'date_of_birth',
                    'x_birthday',
                    'x_studio_birthday',
                    'x_studio_cumpleanos',
                    'x_studio_fecha_nacimiento',
                )
                if field_name in self.Partner._fields
            ),
            False,
        )
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
        self.student_product = self.env['product.product'].create(
            {
                'name': 'Plan Estudiante POS',
                'detailed_type': 'service',
                'list_price': 120.0,
                'sale_ok': True,
                'available_in_pos': True,
                'recurring_invoice': True,
                'wgs_student_age_lock': True,
            }
        )
        self.day_pass_product = self.env['product.product'].create(
            {
                'name': 'Pase 1 día POS',
                'detailed_type': 'service',
                'list_price': 80.0,
                'sale_ok': True,
                'available_in_pos': True,
                'recurring_invoice': True,
                'wgs_single_day_access': True,
            }
        )
        self.family_product = self.env['product.product'].create(
            {
                'name': 'Plan Familiar POS',
                'detailed_type': 'service',
                'list_price': 319.0,
                'sale_ok': True,
                'available_in_pos': True,
                'recurring_invoice': True,
                'wgs_requires_family_authorization': True,
            }
        )
        self.trial_product = self.env['product.product'].create(
            {
                'name': 'Trial gratis POS',
                'detailed_type': 'service',
                'list_price': 0.0,
                'sale_ok': True,
                'available_in_pos': True,
                'recurring_invoice': True,
                'wgs_free_trial_day': True,
            }
        )
        self.plan = self.env['sale.subscription.plan'].create(
            {
                'name': 'Plan test descuentos POS',
                'recurring_interval': 1,
                'recurring_rule_type': 'month',
            }
        )

    def _create_subscription_like_order(self, partner, *, end_date='2026-03-01'):
        order = self.env['sale.order'].create(
            {
                'partner_id': partner.id,
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
        order.action_confirm()
        line = order.order_line[:1]
        line_updates = {}
        for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
            if field_name in line._fields:
                line_updates[field_name] = self.plan.id
        if line_updates:
            line.write(line_updates)
        order_updates = {}
        if 'subscription_state' in order._fields:
            order_updates['subscription_state'] = 'closed'
        for field_name in ('end_date', 'date_end', 'subscription_end_date', 'recurring_end_date'):
            if field_name in order._fields:
                order_updates[field_name] = end_date
                break
        if order_updates:
            order.write(order_updates)
        return order

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

        result = self.PosOrder.sudo().wgs_update_partner_curp_for_pos(
            partner.id,
            'abcd 010101 hdfrrn09',
        )

        self.assertFalse(result['ok'])
        self.assertIn('ABCD010101HDFRRN09', result['error_message'])

    def test_update_partner_for_pos_updates_general_fields(self):
        partner = self.Partner.create({'name': 'Cliente edición POS'})

        result = self.PosOrder.sudo().wgs_update_partner_for_pos(
            partner.id,
            {
                'name': 'Cliente edición POS actualizada',
                'phone': '4491234567',
                'email': 'cliente@example.com',
                'curp': 'mopl-900101-mdfabc01',
            },
        )

        partner.invalidate_recordset(['name', 'phone', 'mobile', 'email', self.curp_field])
        self.assertTrue(result['ok'])
        self.assertEqual(partner.name, 'Cliente edición POS actualizada')
        self.assertEqual(partner.phone, '4491234567')
        self.assertEqual(partner.mobile, '4491234567')
        self.assertEqual(partner.email, 'cliente@example.com')
        self.assertEqual(partner[self.curp_field], 'MOPL900101MDFABC01')

    def test_product_catalog_exposes_curp_requirement(self):
        catalog = self.PosOrder.sudo().wgs_get_subscription_product_catalog_for_pos(limit=20)
        item = next((row for row in catalog if row['id'] == self.product.id), None)

        self.assertTrue(item)
        self.assertTrue(item['requires_curp'])

    def test_student_product_context_requires_curp(self):
        context = self.PosOrder.sudo().wgs_get_subscription_product_context_for_pos(
            self.student_product.id,
            fallback=120.0,
        )

        self.assertTrue(context['student_age_lock'])
        self.assertTrue(context['requires_curp'])

    def test_validate_subscription_product_eligibility_rejects_age_25_or_more(self):
        partner = self.Partner.create(
            {
                'name': 'Cliente estudiante excedido',
                self.curp_field: 'ABCD990101HDFRRN09',
            }
        )

        result = self.PosOrder.sudo().wgs_validate_subscription_product_eligibility_for_pos(
            partner.id,
            self.student_product.id,
        )

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_code'], 'student_age_limit')

    def test_validate_subscription_product_eligibility_accepts_under_25(self):
        partner = self.Partner.create(
            {
                'name': 'Cliente estudiante vigente',
                self.curp_field: 'ABCD080101HDFRRNA9',
            }
        )

        result = self.PosOrder.sudo().wgs_validate_subscription_product_eligibility_for_pos(
            partner.id,
            self.student_product.id,
        )

        self.assertTrue(result['ok'])
        self.assertTrue(result['student_age_lock'])

    def test_curp_birthdate_interprets_02_as_2002(self):
        birthdate = self.PosOrder.sudo()._wgs_get_birthdate_from_curp_for_pos('PEKA020202DERFNR01')
        self.assertEqual(fields.Date.to_string(birthdate), '2002-02-02')

    def test_validate_subscription_product_eligibility_accepts_2002_birth_year(self):
        partner = self.Partner.create(
            {
                'name': 'Cliente 2002 válido',
                self.curp_field: 'PEKA020202DERFNR01',
            }
        )

        result = self.PosOrder.sudo().wgs_validate_subscription_product_eligibility_for_pos(
            partner.id,
            self.student_product.id,
        )

        self.assertTrue(result['ok'])

    def test_product_context_exposes_single_day_and_trial_flags(self):
        context = self.PosOrder.sudo().wgs_get_subscription_product_context_for_pos(
            self.day_pass_product.id,
            fallback=80.0,
        )
        self.assertTrue(context['single_day_access'])

        trial_context = self.PosOrder.sudo().wgs_get_subscription_product_context_for_pos(
            self.trial_product.id,
            fallback=0.0,
        )
        self.assertTrue(trial_context['free_trial_day'])
        self.assertTrue(trial_context['requires_curp'])

    def test_validate_subscription_product_eligibility_blocks_reused_free_trial(self):
        partner = self.Partner.create(
            {
                'name': 'Cliente trial usado',
                self.curp_field: 'ABCD020202HDFRRN01',
            }
        )
        self.env['sale.order'].create(
            {
                'partner_id': partner.id,
                'order_line': [
                    Command.create(
                        {
                            'name': self.trial_product.display_name,
                            'product_id': self.trial_product.id,
                            'product_uom_qty': 1,
                            'price_unit': 0.0,
                        }
                    )
                ],
            }
        )

        result = self.PosOrder.sudo().wgs_validate_subscription_product_eligibility_for_pos(
            partner.id,
            self.trial_product.id,
        )

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_code'], 'free_trial_already_used')

    def test_validate_subscription_product_eligibility_blocks_free_trial_outside_new_flow(self):
        partner = self.Partner.create(
            {
                'name': 'Cliente trial reenroll',
                self.curp_field: 'ABCD020202HDFRRN01',
            }
        )

        result = self.PosOrder.sudo().wgs_validate_subscription_product_eligibility_for_pos(
            partner.id,
            self.trial_product.id,
            'reenroll',
            False,
        )

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_code'], 'free_trial_invalid_flow')

    def test_get_subscription_discount_offers_for_pos_supports_comeback(self):
        partner = self.Partner.create({'name': 'Cliente regreso POS'})
        self._create_subscription_like_order(partner, end_date='2026-03-01')

        offers = self.PosOrder.sudo().wgs_get_subscription_discount_offers_for_pos(
            partner.id,
            self.product.id,
            'new',
            False,
        )

        codes = {offer['code'] for offer in offers}
        self.assertIn('comeback_10', codes)
        self.assertIn('comeback_20', codes)

    def test_get_subscription_discount_offers_for_pos_supports_birthday_once_per_year(self):
        if not self.birthday_field:
            self.skipTest('No existe campo de cumpleaños en este runtime.')

        today = fields.Date.context_today(self.PosOrder)
        partner = self.Partner.create(
            {
                'name': 'Cliente cumpleaños POS',
                self.birthday_field: fields.Date.to_string(today.replace(year=2000)),
            }
        )

        offers = self.PosOrder.sudo().wgs_get_subscription_discount_offers_for_pos(
            partner.id,
            self.product.id,
            'renewal',
            False,
        )

        codes = {offer['code'] for offer in offers}
        self.assertIn('birthday_10', codes)

    def test_authorize_subscription_discount_for_pos_validates_pin(self):
        partner = self.Partner.create({'name': 'Cliente autorización POS'})
        self._create_subscription_like_order(partner, end_date='2026-03-01')
        employee = self.Employee.create(
            {
                'name': 'Supervisor POS',
                'wgs_authorization_pin2': '2468',
            }
        )

        result = self.PosOrder.sudo().wgs_authorize_subscription_discount_for_pos(
            partner.id,
            self.product.id,
            'new',
            'comeback_10',
            '2468',
            False,
        )

        self.assertTrue(result['ok'])
        self.assertEqual(result['authorized_employee_id'], employee.id)
        self.assertEqual(result['discount_percent'], 10.0)

    def test_family_product_returns_only_authorization_offer(self):
        partner = self.Partner.create({'name': 'Cliente familiar POS'})

        offers = self.PosOrder.sudo().wgs_get_subscription_discount_offers_for_pos(
            partner.id,
            self.family_product.id,
            'new',
            False,
        )

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]['code'], 'family_authorization')
        self.assertEqual(float(offers[0]['discount_percent']), 0.0)

    def test_day_pass_is_allowed_in_reenroll_flow(self):
        partner = self.Partner.create({'name': 'Cliente day pass reinscripción'})

        result = self.PosOrder.sudo().wgs_validate_subscription_product_eligibility_for_pos(
            partner.id,
            self.day_pass_product.id,
            'reenroll',
            False,
        )

        self.assertTrue(result['ok'])

    def test_day_pass_and_trial_do_not_require_supervisor_authorization(self):
        partner = self.Partner.create(
            {
                'name': 'Cliente day pass POS',
                self.curp_field: 'ABCD020202HDFRRN01',
            }
        )

        day_pass_offers = self.PosOrder.sudo().wgs_get_subscription_discount_offers_for_pos(
            partner.id,
            self.day_pass_product.id,
            'new',
            False,
        )
        trial_offers = self.PosOrder.sudo().wgs_get_subscription_discount_offers_for_pos(
            partner.id,
            self.trial_product.id,
            'new',
            False,
        )

        self.assertFalse(any(offer['code'] == 'single_day_authorization' for offer in day_pass_offers))
        self.assertFalse(any(offer['code'] == 'free_trial_authorization' for offer in trial_offers))
