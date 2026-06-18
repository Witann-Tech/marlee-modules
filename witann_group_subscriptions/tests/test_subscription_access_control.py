from odoo import fields
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
        self.site_b = self.env['access_control.site'].create(
            {
                'name': 'Centro acceso B',
                'code': 'MX-ACB',
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
                'state': 'sale',
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
        progress_state = self._find_subscription_state_value('progress', 'en progreso')

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

    def test_draft_subscription_state_does_not_grant_access(self):
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
        progress_state = self._find_subscription_state_value('progress', 'en progreso')

        order.write({'subscription_state': progress_state})

        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)

        self.assertFalse(owner_person and owner_person.active)
        self.assertFalse(participant_person and participant_person.active)

    def test_manual_access_block_overrides_active_subscription(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso')

        order.write({'subscription_state': progress_state})
        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        self.assertTrue(owner_person.active)
        self.assertEqual(owner_person.access_state, 'enabled')

        self.owner.write(
            {
                'wgs_access_blocked': True,
                'wgs_access_block_reason': 'Bloqueo de prueba',
                'wgs_access_blocked_at': fields.Datetime.now(),
                'wgs_access_blocked_by_id': self.env.user.id,
            }
        )

        owner_person.invalidate_recordset(['active', 'access_state'])
        self.assertFalse(owner_person.active)
        self.assertEqual(owner_person.access_state, 'suspended')

        self.owner.write(
            {
                'wgs_access_blocked': False,
                'wgs_access_block_reason': False,
                'wgs_access_blocked_at': False,
                'wgs_access_blocked_by_id': False,
            }
        )

        owner_person.invalidate_recordset(['active', 'access_state'])
        self.assertTrue(owner_person.active)
        self.assertEqual(owner_person.access_state, 'enabled')

    def test_direct_partner_access_block_only_changes_that_partner(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso')

        order.write({'subscription_state': progress_state})
        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)
        self.assertTrue(owner_person.active)
        self.assertTrue(participant_person.active)

        self.owner.write(
            {
                'wgs_access_blocked': True,
                'wgs_access_block_reason': 'Bloqueo directo solo titular',
                'wgs_access_blocked_at': fields.Datetime.now(),
                'wgs_access_blocked_by_id': self.env.user.id,
            }
        )

        owner_person.invalidate_recordset(['active', 'access_state'])
        participant_person.invalidate_recordset(['active', 'access_state'])
        self.assertFalse(owner_person.active)
        self.assertEqual(owner_person.access_state, 'suspended')
        self.assertTrue(participant_person.active)
        self.assertEqual(participant_person.access_state, 'enabled')

    def test_paused_subscription_suspends_access_without_deleting_person(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso')
        pause_state = self._find_subscription_state_value('pause', 'pausa', 'hold', 'suspend')

        order.write({'subscription_state': progress_state})
        order.write({'subscription_state': pause_state})

        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)

        self.assertFalse(owner_person.active)
        self.assertFalse(participant_person.active)
        self.assertEqual(owner_person.access_state, 'suspended')
        self.assertEqual(participant_person.access_state, 'suspended')

    def test_renew_subscription_deactivates_access(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso')
        renew_state = self._find_subscription_state_value('renew', 'to renew', 'por renovar')

        order.write({'subscription_state': progress_state})
        order.write({'subscription_state': renew_state})

        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)

        self.assertTrue(owner_person)
        self.assertTrue(participant_person)
        self.assertFalse(owner_person.active)
        self.assertFalse(participant_person.active)
        self.assertEqual(owner_person.access_state, 'suspended')
        self.assertEqual(participant_person.access_state, 'suspended')

    def test_expired_progress_subscription_deactivates_access(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso')
        next_field = next(
            (
                field_name
                for field_name in ('recurring_next_date', 'next_invoice_date', 'recurring_next_invoice_date')
                if field_name in order._fields
            ),
            False,
        )
        if not next_field:
            self.skipTest('No existe campo de próxima fecha de cobro en este runtime.')

        order.write({'subscription_state': progress_state})
        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        self.assertTrue(owner_person.active)

        order.write({next_field: fields.Date.context_today(order)})

        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)

        self.assertFalse(owner_person.active)
        self.assertFalse(participant_person.active)

    def test_cancelled_subscription_deactivates_managed_people(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso')
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
        progress_state = self._find_subscription_state_value('progress', 'en progreso')
        pause_state = self._find_subscription_state_value('pause', 'pausa', 'hold', 'suspend')

        active_order = self._create_subscription_order()
        active_order.write({'subscription_state': progress_state})

        paused_order = self._create_subscription_order()
        paused_order.write({'subscription_state': pause_state})

        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)

        self.assertEqual(owner_person.access_state, 'enabled')
        self.assertEqual(participant_person.access_state, 'enabled')

    def test_configured_access_sites_override_company_wide_sites(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso')
        self.product.product_tmpl_id.write({'wgs_access_site_ids': [Command.set([self.site_b.id])]})

        order.write({'subscription_state': progress_state})

        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)

        self.assertEqual(set(owner_person.site_ids.ids), {self.site_b.id})
        self.assertEqual(set(participant_person.site_ids.ids), {self.site_b.id})

    def test_changing_product_access_sites_resyncs_existing_subscribers(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso')
        order.write({'subscription_state': progress_state})
        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)
        self.assertEqual(set(owner_person.site_ids.ids), {self.site.id})
        self.assertEqual(set(participant_person.site_ids.ids), {self.site.id})

        self.env['access_control.sync_change'].search([]).unlink()
        self.product.product_tmpl_id.write({'wgs_access_site_ids': [Command.set([self.site.id, self.site_b.id])]})
        owner_person.invalidate_recordset(['site_ids'])
        participant_person.invalidate_recordset(['site_ids'])
        changes = self.env['access_control.sync_change'].search(
            [
                ('person_id', 'in', [owner_person.id, participant_person.id]),
                ('site_id', '=', self.site_b.id),
                ('action', '=', 'upsert'),
            ]
        )

        self.assertEqual(set(owner_person.site_ids.ids), {self.site.id, self.site_b.id})
        self.assertEqual(set(participant_person.site_ids.ids), {self.site.id, self.site_b.id})
        self.assertEqual(len(changes), 2)
        self.assertTrue(all(changes.mapped('priority')))

    def test_changing_product_access_timezone_resyncs_existing_subscribers(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso')
        order.write({'subscription_state': progress_state})
        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)
        general_timezone = self.env.ref('access_control_api.access_timezone_general')
        restricted_timezone = self.env['access_control.timezone'].create(
            {
                'name': 'Matutino prueba',
            }
        )
        self.assertEqual(owner_person.access_timezone_id, general_timezone)
        self.assertEqual(participant_person.access_timezone_id, general_timezone)

        self.env['access_control.sync_change'].search([]).unlink()
        self.product.product_tmpl_id.write({'wgs_access_timezone_id': restricted_timezone.id})
        owner_person.invalidate_recordset(['access_timezone_id'])
        participant_person.invalidate_recordset(['access_timezone_id'])
        changes = self.env['access_control.sync_change'].search(
            [
                ('person_id', 'in', [owner_person.id, participant_person.id]),
                ('site_id', '=', self.site.id),
                ('action', '=', 'upsert'),
            ]
        )

        self.assertEqual(owner_person.access_timezone_id, restricted_timezone)
        self.assertEqual(participant_person.access_timezone_id, restricted_timezone)
        self.assertEqual(len(changes), 2)
        self.assertTrue(all(changes.mapped('priority')))

    def test_changing_variant_access_timezone_resyncs_existing_subscribers(self):
        order = self._create_subscription_order()
        progress_state = self._find_subscription_state_value('progress', 'en progreso')
        order.write({'subscription_state': progress_state})
        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)
        restricted_timezone = self.env['access_control.timezone'].create(
            {
                'name': 'Vespertino prueba',
            }
        )

        self.env['access_control.sync_change'].search([]).unlink()
        self.product.write({'wgs_access_timezone_id': restricted_timezone.id})
        owner_person.invalidate_recordset(['access_timezone_id'])
        participant_person.invalidate_recordset(['access_timezone_id'])
        changes = self.env['access_control.sync_change'].search(
            [
                ('person_id', 'in', [owner_person.id, participant_person.id]),
                ('site_id', '=', self.site.id),
                ('action', '=', 'upsert'),
            ]
        )

        self.assertEqual(owner_person.access_timezone_id, restricted_timezone)
        self.assertEqual(participant_person.access_timezone_id, restricted_timezone)
        self.assertEqual(len(changes), 2)
        self.assertTrue(all(changes.mapped('priority')))

    def test_access_sites_are_aggregated_across_multisite_subscriptions(self):
        progress_state = self._find_subscription_state_value('progress', 'en progreso')

        self.product.product_tmpl_id.write({'wgs_access_site_ids': [Command.set([self.site.id])]})
        order_a = self._create_subscription_order()
        order_a.write({'subscription_state': progress_state})

        second_product = self.product.copy({
            'name': 'Plan acceso multisede',
            'max_participants_total': 3,
        })
        second_product.product_tmpl_id.write({'wgs_access_site_ids': [Command.set([self.site_b.id])]})
        order_b = self.env['sale.order'].create(
            {
                'partner_id': self.owner.id,
                'company_id': self.env.company.id,
                'state': 'sale',
                'order_line': [
                    Command.create(
                        {
                            'product_id': second_product.id,
                            'name': second_product.name,
                            'product_uom_qty': 1,
                            'product_uom': second_product.uom_id.id,
                            'price_unit': second_product.list_price,
                        }
                    )
                ],
            }
        )
        order_b.write({'participant_ids': [Command.set([self.owner.id, self.participant.id])]})
        order_b.write({'subscription_state': progress_state})

        owner_person = self.env['access_control.person'].search([('partner_id', '=', self.owner.id)], limit=1)
        participant_person = self.env['access_control.person'].search([('partner_id', '=', self.participant.id)], limit=1)

        self.assertEqual(set(owner_person.site_ids.ids), {self.site.id, self.site_b.id})
        self.assertEqual(set(participant_person.site_ids.ids), {self.site.id, self.site_b.id})
