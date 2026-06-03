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
