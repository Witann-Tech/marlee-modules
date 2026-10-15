"""Extend WGS lifecycle ownership with paid POS commercial operations."""

from odoo import api, fields, models
from odoo.fields import Domain


class SaleOrderPosLifecycle(models.Model):
    _inherit = 'sale.order'

    wgs_pos_applied_line_ids = fields.One2many(
        'pos.order.line', 'wgs_sale_order_id', readonly=True, copy=False,
    )

    @api.model
    def _wgs_managed_subscription_domain(self):
        paid = Domain([
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
            ('qty', '>', 0),
            # Paying a native invoice alone does not transfer its billing engine.
            ('wgs_subscription_flow', 'in', [False, 'new', 'renewal', 'reenroll', 'upsale']),
        ])
        return super()._wgs_managed_subscription_domain() | (
            Domain('wgs_pos_applied_line_ids', 'any', paid)
            | Domain('wgs_subscription_operation_line_ids', 'any', paid)
        )
