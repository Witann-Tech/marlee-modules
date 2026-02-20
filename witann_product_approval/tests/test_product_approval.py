from odoo import fields
from odoo.tests import common


class TestProductApproval(common.TransactionCase):
    def setUp(self):
        super().setUp()
        self.ProductTemplate = self.env['product.template']
        self.product = self.ProductTemplate.create(
            {
                'name': 'Producto de prueba',
                'sale_ok': True,
                'list_price': 10.0,
            }
        )

    def test_admin_write_sets_approved(self):
        self.product.write({'list_price': 22.0})
        self.assertEqual(self.product.approval_state, 'approved')
        self.assertEqual(self.product.list_price, 22.0)

    def test_approve_pending_create(self):
        product = self.ProductTemplate.with_context(skip_product_approval=False).create(
            {
                'name': 'Producto pendiente',
                'sale_ok': True,
                'list_price': 19.0,
            }
        )
        # Con superusuario queda aprobado de inmediato.
        self.assertEqual(product.approval_state, 'approved')

    def test_reject_pending_changes(self):
        # Simula una solicitud pendiente creada por un flujo externo.
        request = self.env['product.template.change.request'].create(
            {
                'product_tmpl_id': self.product.id,
                'change_type': 'update',
                'payload': {'list_price': 35.0},
                'state': 'pending',
                'requested_by_id': self.env.user.id,
                'requested_on': fields.Datetime.now(),
            }
        )
        self.product.with_context(skip_product_approval=True).write(
            {
                'approval_state': 'pending',
                'last_change_request_id': request.id,
            }
        )

        self.product.action_reject_pending_changes()
        self.assertEqual(self.product.approval_state, 'rejected')
        self.assertEqual(request.state, 'rejected')
