from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestPosInvoiceLock(TransactionCase):
    def test_invoice_action_is_blocked_for_pos_orders(self):
        with self.assertRaises(UserError):
            self.env['pos.order'].action_pos_order_invoice()
