from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests.common import TransactionCase


class TestSubscriptionParticipants(TransactionCase):
    def setUp(self):
        super().setUp()
        self.partner_owner = self.env['res.partner'].create({'name': 'Titular'})
        self.partners = self.env['res.partner'].create(
            [
                {'name': 'Participante 1'},
                {'name': 'Participante 2'},
                {'name': 'Participante 3'},
                {'name': 'Participante 4'},
                {'name': 'Participante 5'},
                {'name': 'Participante 6'},
                {'name': 'Participante 7'},
            ]
        )

        self.subscription_product = self.env['product.product'].create(
            {
                'name': 'Plan Familiar',
                'detailed_type': 'service',
                'list_price': 100,
                'recurring_invoice': True,
                'max_participants_total': 3,
            }
        )

        self.non_subscription_product = self.env['product.product'].create(
            {
                'name': 'Toalla',
                'detailed_type': 'consu',
                'list_price': 10,
            }
        )

    def _create_subscription_order(self, qty=1):
        return self.env['sale.order'].create(
            {
                'partner_id': self.partner_owner.id,
                'order_line': [
                    Command.create(
                        {
                            'product_id': self.subscription_product.id,
                            'name': self.subscription_product.name,
                            'product_uom_qty': qty,
                            'product_uom': self.subscription_product.uom_id.id,
                            'price_unit': self.subscription_product.list_price,
                        }
                    )
                ],
            }
        )

    def test_owner_is_added_automatically(self):
        order = self._create_subscription_order(qty=1)

        self.assertTrue(order.subscription_has_recurring_products)
        self.assertEqual(order.subscription_max_participants_total, 3)
        self.assertIn(self.partner_owner, order.participant_ids)

    def test_limit_is_qty_times_product_capacity(self):
        order = self._create_subscription_order(qty=2)

        allowed_ids = [self.partner_owner.id] + self.partners[:5].ids
        order.write({'participant_ids': [Command.set(allowed_ids)]})
        self.assertEqual(len(order.participant_ids), 6)

        with self.assertRaises(ValidationError):
            order.write(
                {
                    'participant_ids': [
                        Command.set([self.partner_owner.id] + self.partners[:6].ids)
                    ]
                }
            )

    def test_owner_is_reinserted_when_removed(self):
        order = self._create_subscription_order(qty=1)

        order.write({'participant_ids': [Command.set(self.partners[:2].ids)]})
        self.assertIn(self.partner_owner, order.participant_ids)

    def test_copy_keeps_participants(self):
        order = self._create_subscription_order(qty=1)
        order.write(
            {
                'participant_ids': [
                    Command.set([self.partner_owner.id, self.partners[0].id, self.partners[1].id])
                ]
            }
        )

        copied_order = order.copy()
        self.assertEqual(
            set(copied_order.participant_ids.ids),
            set(order.participant_ids.ids),
        )

    def test_non_subscription_products_do_not_force_participants(self):
        order = self.env['sale.order'].create(
            {
                'partner_id': self.partner_owner.id,
                'order_line': [
                    Command.create(
                        {
                            'product_id': self.non_subscription_product.id,
                            'name': self.non_subscription_product.name,
                            'product_uom_qty': 1,
                            'product_uom': self.non_subscription_product.uom_id.id,
                            'price_unit': self.non_subscription_product.list_price,
                        }
                    )
                ],
            }
        )

        self.assertFalse(order.subscription_has_recurring_products)
        self.assertEqual(order.subscription_max_participants_total, 0)
        self.assertFalse(order.participant_ids)

    def test_zero_qty_recurring_line_is_ignored_for_capacity(self):
        order = self._create_subscription_order(qty=0)

        self.assertFalse(order.subscription_has_recurring_products)
        self.assertEqual(order.subscription_max_participants_total, 0)
        self.assertFalse(order.participant_ids)

        selected_participants = self.partners[:4].ids
        order.write({'participant_ids': [Command.set(selected_participants)]})
        self.assertEqual(set(order.participant_ids.ids), set(selected_participants))
