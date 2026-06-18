from datetime import date, datetime

from odoo.tests.common import TransactionCase
from odoo import Command, fields
from odoo.exceptions import ValidationError


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

    def _create_subscription_like_order(
        self,
        partner,
        *,
        end_date='2026-03-01',
        subscription_state='closed',
        next_invoice_date=False,
    ):
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
            order_updates['subscription_state'] = subscription_state
        if next_invoice_date:
            for field_name in ('recurring_next_date', 'next_invoice_date'):
                if field_name in order._fields:
                    order_updates[field_name] = next_invoice_date
                    break
        for field_name in ('end_date', 'date_end', 'subscription_end_date', 'recurring_end_date'):
            if field_name in order._fields:
                order_updates[field_name] = end_date
                break
        if order_updates:
            order.write(order_updates)
        return order

    def test_validate_subscription_product_eligibility_blocks_new_when_partner_has_active_subscription(self):
        partner = self.Partner.create({'name': 'Cliente activo bloqueado'})
        self._create_subscription_like_order(
            partner,
            subscription_state='progress',
            end_date='2026-12-31',
            next_invoice_date='2026-06-01',
        )

        result = self.PosOrder.sudo().wgs_validate_subscription_product_eligibility_for_pos(
            partner.id,
            self.product.id,
            'new',
            False,
        )

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_code'], 'active_subscription_exists')

    def test_pricing_for_new_blocks_when_partner_has_active_subscription(self):
        partner = self.Partner.create({'name': 'Cliente activo quote bloqueado'})
        self._create_subscription_like_order(
            partner,
            subscription_state='renew',
            end_date='2026-12-31',
            next_invoice_date='2026-05-01',
        )

        with self.assertRaisesRegex(Exception, 'upsale o una renovación'):
            self.PosOrder.sudo().wgs_get_subscription_pricing_for_pos(
                partner_id=partner.id,
                product_id=self.product.id,
                flow='new',
                source_subscription_id=False,
                pending_move_id=False,
                fallback=100.0,
                preferred_plan_id=False,
                preferred_pricing_id=False,
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

    def test_product_catalog_reuses_subscription_flags_helper(self):
        catalog = self.PosOrder.sudo().wgs_get_subscription_product_catalog_for_pos(limit=20)
        day_pass = next((row for row in catalog if row['id'] == self.day_pass_product.id), None)
        family = next((row for row in catalog if row['id'] == self.family_product.id), None)
        trial = next((row for row in catalog if row['id'] == self.trial_product.id), None)

        self.assertTrue(day_pass)
        self.assertTrue(day_pass['single_day_access'])
        self.assertFalse(day_pass['free_trial_day'])
        self.assertTrue(family)
        self.assertTrue(family['family_authorization'])
        self.assertTrue(trial)
        self.assertTrue(trial['free_trial_day'])
        self.assertTrue(trial['requires_curp'])

    def test_student_product_pricing_requires_curp(self):
        payload = self.PosOrder.sudo().wgs_get_subscription_pricing_for_pos(
            partner_id=self.partner.id,
            product_id=self.student_product.id,
            flow='new',
            source_subscription_id=False,
            pending_move_id=False,
            fallback=120.0,
            preferred_plan_id=False,
            preferred_pricing_id=False,
        )

        self.assertTrue(payload['student_age_lock'])
        self.assertTrue(payload['requires_curp'])

    def test_validate_subscription_product_eligibility_rejects_age_26_or_more(self):
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

    def test_validate_subscription_product_eligibility_accepts_under_26(self):
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

    def test_pricing_payload_exposes_single_day_and_trial_flags(self):
        payload = self.PosOrder.sudo().wgs_get_subscription_pricing_for_pos(
            partner_id=self.partner.id,
            product_id=self.day_pass_product.id,
            flow='new',
            source_subscription_id=False,
            pending_move_id=False,
            fallback=80.0,
            preferred_plan_id=False,
            preferred_pricing_id=False,
        )
        self.assertTrue(payload['single_day_access'])

        trial_payload = self.PosOrder.sudo().wgs_get_subscription_pricing_for_pos(
            partner_id=self.partner.id,
            product_id=self.trial_product.id,
            flow='new',
            source_subscription_id=False,
            pending_move_id=False,
            fallback=0.0,
            preferred_plan_id=False,
            preferred_pricing_id=False,
        )
        self.assertTrue(trial_payload['free_trial_day'])
        self.assertTrue(trial_payload['requires_curp'])

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

    def test_subscription_discount_offers_are_no_longer_condition_based(self):
        partner = self.Partner.create({'name': 'Cliente regreso POS'})
        self._create_subscription_like_order(partner, end_date='2026-03-01')

        offers = self.PosOrder.sudo().wgs_get_subscription_discount_offers_for_pos(
            partner.id,
            self.product.id,
            'new',
            False,
        )

        self.assertEqual(offers, [])

    def test_authorize_subscription_discount_for_pos_validates_pin_and_percent(self):
        partner = self.Partner.create({'name': 'Cliente autorización POS'})
        employee = self.Employee.create(
            {
                'name': 'Supervisor POS',
                'pin': '2468',
                'wgs_authorization_pin': '135790',
            }
        )

        rejected = self.PosOrder.sudo().wgs_authorize_subscription_discount_for_pos(
            partner.id,
            self.product.id,
            'new',
            10,
            '2468',
            False,
        )
        self.assertFalse(rejected['ok'])

        invalid_percent = self.PosOrder.sudo().wgs_authorize_subscription_discount_for_pos(
            partner.id,
            self.product.id,
            'new',
            0,
            '135790',
            False,
        )
        self.assertFalse(invalid_percent['ok'])

        result = self.PosOrder.sudo().wgs_authorize_subscription_discount_for_pos(
            partner.id,
            self.product.id,
            'new',
            12.5,
            '135790',
            False,
        )

        self.assertTrue(result['ok'])
        self.assertEqual(result['authorized_employee_id'], employee.id)
        self.assertEqual(result['code'], 'manual_percent')
        self.assertEqual(result['discount_percent'], 12.5)

    def test_subscription_line_price_lock_uses_snapshot_and_wgs_discount(self):
        values = self.PosOrder.sudo()._wgs_get_locked_subscription_line_price_values_for_pos(
            {
                'pricing_snapshot': {
                    'ticket_charge_now': 799.0,
                },
                'discount_code': 'manual_percent',
                'discount_percent': 12.5,
                'discount_authorized_employee_id': 1,
                'discount_authorized_at': '2026-05-29 12:00:00',
            },
            fallback_price=1.0,
        )

        self.assertEqual(values['price_unit'], 799.0)
        self.assertEqual(values['discount'], 12.5)

    def test_subscription_line_price_lock_rejects_unauthorized_discount(self):
        values = self.PosOrder.sudo()._wgs_get_locked_subscription_line_price_values_for_pos(
            {
                'pricing_snapshot': {
                    'ticket_charge_now': 799.0,
                },
                'discount_percent': 50.0,
            },
            fallback_price=1.0,
        )

        self.assertEqual(values['price_unit'], 799.0)
        self.assertEqual(values['discount'], 0.0)

    def test_subscription_line_price_lock_preserves_zero_charge(self):
        values = self.PosOrder.sudo()._wgs_get_locked_subscription_line_price_values_for_pos(
            {
                'pricing_snapshot': {
                    'ticket_charge_now': 0.0,
                    'ticket_recurring_price': 999.0,
                },
                'discount_percent': 0.0,
            },
            fallback_price=1.0,
        )

        self.assertEqual(values['price_unit'], 0.0)
        self.assertEqual(values['discount'], 0.0)

    def test_authorization_pin_is_separate_from_pos_pin(self):
        with self.assertRaises(ValidationError):
            self.Employee.create(
                {
                    'name': 'Supervisor PIN duplicado',
                    'pin': '2468',
                    'wgs_authorization_pin': '2468',
                }
            )

        self.Employee.create(
            {
                'name': 'Supervisor uno',
                'wgs_authorization_pin': '975310',
            }
        )
        with self.assertRaises(ValidationError):
            self.Employee.create(
                {
                    'name': 'Supervisor dos',
                    'wgs_authorization_pin': '975310',
                }
            )

    def test_authorization_pin_rotation_uses_calendar_days(self):
        employee = self.Employee.create(
            {
                'name': 'Supervisor rotación diaria',
                'work_email': 'supervisor@example.invalid',
                'wgs_authorization_pin': '135790',
            }
        )
        credential = employee._wgs_authorization_credential()
        credential.write({'last_rotated_at': fields.Datetime.to_string(datetime(2026, 5, 31, 23, 30, 0))})

        due = self.Employee._wgs_authorization_pin_rotation_due_credentials(1, today=date(2026, 6, 1))

        self.assertIn(credential, due)

    def test_family_product_does_not_create_conditional_discount_offer(self):
        partner = self.Partner.create({'name': 'Cliente familiar POS'})

        offers = self.PosOrder.sudo().wgs_get_subscription_discount_offers_for_pos(
            partner.id,
            self.family_product.id,
            'new',
            False,
        )

        self.assertEqual(offers, [])

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
