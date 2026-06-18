from odoo import Command
from odoo.tests.common import TransactionCase


class TestPosAccessBlock(TransactionCase):
    def setUp(self):
        super().setUp()
        self.owner = self.env['res.partner'].create({'name': 'Titular POS acceso'})
        self.participant = self.env['res.partner'].create({'name': 'Participante POS acceso'})
        self.site = self.env['access_control.site'].create(
            {
                'name': 'Centro POS acceso',
                'code': 'MX-POS-ACC',
                'company_id': self.env.company.id,
            }
        )
        self.product = self.env['product.product'].create(
            {
                'name': 'Plan POS acceso',
                'detailed_type': 'service',
                'list_price': 100,
                'recurring_invoice': True,
                'max_participants_total': 2,
            }
        )
        self.other_company = self.env['res.company'].create({'name': 'Otra empresa POS acceso'})
        self.other_site = self.env['access_control.site'].create(
            {
                'name': 'Centro POS acceso otra empresa',
                'code': 'MX-POS-ACC-OTHER',
                'company_id': self.other_company.id,
            }
        )
        self.other_product = self.product.copy({'name': 'Plan POS acceso otra empresa'})
        if 'company_id' in self.other_product.product_tmpl_id._fields:
            self.other_product.product_tmpl_id.write({'company_id': self.other_company.id})
        elif 'company_id' in self.other_product._fields:
            self.other_product.write({'company_id': self.other_company.id})
        self.env.user.write(
            {
                'groups_id': [
                    Command.link(self.env.ref('point_of_sale.group_pos_user').id),
                ]
            }
        )

    def _find_subscription_state_value(self, *tokens):
        field = self.env['sale.order']._fields.get('subscription_state')
        if not field:
            self.skipTest('sale.order no expone subscription_state en este runtime.')
        selection = field.selection
        if callable(selection):
            try:
                selection = selection(self.env['sale.order'])
            except TypeError:
                selection = selection(self.env)
        lowered_tokens = tuple(str(token).lower() for token in tokens)
        for value, label in selection or []:
            haystack = ' '.join(filter(None, [str(value).lower(), str(label).lower()]))
            if any(token in haystack for token in lowered_tokens):
                return value
        self.skipTest('No se encontró un estado de suscripción compatible con tokens: %s' % (tokens,))

    def _create_subscription_order(self):
        order = self.env['sale.order'].create(
            {
                'partner_id': self.owner.id,
                'company_id': self.env.company.id,
                'order_line': [
                    Command.create(
                        {
                            'product_id': self.product.id,
                            'name': self.product.name,
                            'product_uom_qty': 1,
                            'product_uom': self.product.uom_id.id,
                            'price_unit': self.product.list_price,
                        }
                    )
                ],
            }
        )
        order.write({'participant_ids': [Command.set([self.owner.id, self.participant.id])]})
        return order

    def _create_other_company_subscription_order(self):
        order = self.env['sale.order'].with_company(self.other_company).sudo().create(
            {
                'partner_id': self.owner.id,
                'company_id': self.other_company.id,
                'order_line': [
                    Command.create(
                        {
                            'product_id': self.other_product.id,
                            'name': self.other_product.name,
                            'product_uom_qty': 1,
                            'product_uom': self.other_product.uom_id.id,
                            'price_unit': self.other_product.list_price,
                        }
                    )
                ],
            }
        )
        order.write({'participant_ids': [Command.set([self.owner.id, self.participant.id])]})
        return order

    def test_pos_access_block_from_participant_applies_to_full_package(self):
        order = self._create_subscription_order()
        order.write({'subscription_state': self._find_subscription_state_value('progress', 'en progreso')})

        Person = self.env['access_control.person']
        owner_person = Person.search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = Person.search([('partner_id', '=', self.participant.id)], limit=1)
        self.assertTrue(owner_person.active)
        self.assertTrue(participant_person.active)

        result = self.env['sale.order'].wgs_block_partner_access_for_pos(
            self.participant.id,
            'Bloqueo de paquete desde participante',
        )
        self.assertTrue(result['ok'])
        self.assertEqual(set(result['affected_partner_ids']), {self.owner.id, self.participant.id})

        owner_person.invalidate_recordset(['active', 'access_state'])
        participant_person.invalidate_recordset(['active', 'access_state'])
        self.owner.invalidate_recordset(['wgs_access_blocked'])
        self.participant.invalidate_recordset(['wgs_access_blocked'])
        self.assertTrue(self.owner.wgs_access_blocked)
        self.assertTrue(self.participant.wgs_access_blocked)
        self.assertFalse(owner_person.active)
        self.assertFalse(participant_person.active)
        self.assertEqual(owner_person.access_state, 'suspended')
        self.assertEqual(participant_person.access_state, 'suspended')

        result = self.env['sale.order'].wgs_unblock_partner_access_for_pos(self.owner.id)
        self.assertTrue(result['ok'])
        self.assertEqual(set(result['affected_partner_ids']), {self.owner.id, self.participant.id})

        owner_person.invalidate_recordset(['active', 'access_state'])
        participant_person.invalidate_recordset(['active', 'access_state'])
        self.owner.invalidate_recordset(['wgs_access_blocked'])
        self.participant.invalidate_recordset(['wgs_access_blocked'])
        self.assertFalse(self.owner.wgs_access_blocked)
        self.assertFalse(self.participant.wgs_access_blocked)
        self.assertTrue(owner_person.active)
        self.assertTrue(participant_person.active)
        self.assertEqual(owner_person.access_state, 'enabled')
        self.assertEqual(participant_person.access_state, 'enabled')

    def test_partner_detail_is_scoped_to_requested_pos_company(self):
        progress_state = self._find_subscription_state_value('progress', 'en progreso')
        current_order = self._create_subscription_order()
        current_order.write({'subscription_state': progress_state})
        other_order = self._create_other_company_subscription_order()
        other_order.write({'subscription_state': progress_state})

        current_detail = self.env['sale.order'].get_partner_subscription_detail_for_pos(
            self.owner.id,
            company_id=self.env.company.id,
        )
        other_detail = self.env['sale.order'].get_partner_subscription_detail_for_pos(
            self.owner.id,
            company_id=self.other_company.id,
        )

        self.assertEqual(
            {item['subscription_id'] for item in current_detail['items']},
            {current_order.id},
        )
        self.assertEqual(
            {item['subscription_id'] for item in other_detail['items']},
            {other_order.id},
        )

    def test_partner_detail_explains_cross_company_access_without_operable_card(self):
        if 'wgs_access_site_ids' not in self.product.product_tmpl_id._fields:
            self.skipTest('El runtime no expone sitios de acceso en producto.')

        progress_state = self._find_subscription_state_value('progress', 'en progreso')
        self.product.product_tmpl_id.write({
            'wgs_access_site_ids': [Command.set([self.site.id, self.other_site.id])],
        })
        current_order = self._create_subscription_order()
        current_order.write({'subscription_state': progress_state})

        other_detail = self.env['sale.order'].get_partner_subscription_detail_for_pos(
            self.owner.id,
            company_id=self.other_company.id,
        )

        self.assertNotIn(current_order.id, {item['subscription_id'] for item in other_detail['items']})
        self.assertEqual(other_detail['state'], 'external_access')
        self.assertEqual(other_detail['state_label'], 'Acceso multisede')
        self.assertEqual(other_detail['access_origin_subscription_id'], current_order.id)
        self.assertIn(self.env.company.display_name, other_detail['access_origin_message'])
        self.assertTrue(other_detail['has_subscription_history'])

        row = self.env['sale.order'].get_partner_directory_row_for_pos(
            self.owner.id,
            company_id=self.other_company.id,
        )
        self.assertEqual(row['state'], 'external_access')
        self.assertIn('origen', row['package_label'].lower())

    def test_partner_detail_explains_cross_company_access_from_person_sites_fallback(self):
        progress_state = self._find_subscription_state_value('progress', 'en progreso')
        current_order = self._create_subscription_order()
        current_order.write({'subscription_state': progress_state})

        person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        self.assertTrue(person)
        person.write({'site_ids': [Command.set([self.site.id, self.other_site.id])]})

        other_detail = self.env['sale.order'].get_partner_subscription_detail_for_pos(
            self.owner.id,
            company_id=self.other_company.id,
        )

        self.assertNotIn(current_order.id, {item['subscription_id'] for item in other_detail['items']})
        self.assertEqual(other_detail['state'], 'external_access')
        self.assertEqual(other_detail['access_origin_subscription_id'], current_order.id)
        self.assertFalse(other_detail.get('subscription_id'))

    def test_partner_detail_explains_manual_access_without_subscription_card(self):
        Person = self.env['access_control.person']
        person = Person.search([('partner_id', '=', self.owner.id)], limit=1)
        values = {
            'active': True,
            'access_state': 'enabled',
            'managed_by_subscription': False,
            'site_ids': [Command.set([self.other_site.id])],
        }
        if person:
            person.write(values)
        else:
            values['partner_id'] = self.owner.id
            Person.create(values)

        other_detail = self.env['sale.order'].get_partner_subscription_detail_for_pos(
            self.owner.id,
            company_id=self.other_company.id,
        )

        self.assertEqual(other_detail['items'], [])
        self.assertEqual(other_detail['state'], 'manual_access')
        self.assertEqual(other_detail['state_label'], 'Acceso manual')
        self.assertEqual(other_detail['package_label'], 'Acceso manual')
        self.assertFalse(other_detail.get('subscription_id'))

        row = self.env['sale.order'].get_partner_directory_row_for_pos(
            self.owner.id,
            company_id=self.other_company.id,
        )
        self.assertEqual(row['state'], 'manual_access')
        self.assertEqual(row['package_label'], 'Acceso manual')
