from odoo.fields import Command
from odoo.tests.common import TransactionCase


class TestSubscriptionAccessControl(TransactionCase):
    def setUp(self):
        super().setUp()
        self.owner = self.env['res.partner'].create({'name': 'Titular acceso'})
        self.participant = self.env['res.partner'].create({'name': 'Participante acceso'})
        self.site = self.env['access_control.site'].create(
            {
                'name': 'Centro acceso',
                'code': 'MX-ACC',
                'company_id': self.env.company.id,
            }
        )
        self.product = self.env['product.product'].create(
            {
                'name': 'Plan acceso',
                'detailed_type': 'service',
                'list_price': 100,
                'recurring_invoice': True,
                'max_participants_total': 3,
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
        selection = selection or []
        lowered_tokens = tuple(str(token).lower() for token in tokens)
        for value, label in selection:
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

    def test_active_subscription_creates_access_people(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso', 'renew', 'por renovar')

        order.write({'subscription_state': progress_state})

        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)

        self.assertTrue(owner_person)
        self.assertTrue(participant_person)
        self.assertTrue(owner_person.active)
        self.assertTrue(participant_person.active)
        self.assertEqual(owner_person.access_state, 'enabled')
        self.assertEqual(participant_person.access_state, 'enabled')
        self.assertEqual(set(owner_person.site_ids.ids), {self.site.id})
        self.assertEqual(set(participant_person.site_ids.ids), {self.site.id})

    def test_paused_subscription_suspends_access_without_deleting_person(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso', 'renew', 'por renovar')
        pause_state = self._find_subscription_state_value('pause', 'pausa', 'hold', 'suspend')

        order.write({'subscription_state': progress_state})
        order.write({'subscription_state': pause_state})

        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)

        self.assertTrue(owner_person.active)
        self.assertTrue(participant_person.active)
        self.assertEqual(owner_person.access_state, 'suspended')
        self.assertEqual(participant_person.access_state, 'suspended')

    def test_cancelled_subscription_deactivates_managed_people(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso', 'renew', 'por renovar')
        cancel_state = self._find_subscription_state_value('cancel', 'churn', 'close')

        order.write({'subscription_state': progress_state})
        order.write({'subscription_state': cancel_state})

        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)

        self.assertTrue(owner_person)
        self.assertTrue(participant_person)
        self.assertFalse(owner_person.active)
        self.assertFalse(participant_person.active)

    def test_access_is_aggregated_across_multiple_subscriptions(self):
        progress_state = self._find_subscription_state_value('progress', 'en progreso', 'renew', 'por renovar')
        pause_state = self._find_subscription_state_value('pause', 'pausa', 'hold', 'suspend')

        active_order = self._create_subscription_order()
        active_order.write({'subscription_state': progress_state})

        paused_order = self._create_subscription_order()
        paused_order.write({'subscription_state': pause_state})

        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)

        self.assertEqual(owner_person.access_state, 'enabled')
        self.assertEqual(participant_person.access_state, 'enabled')
