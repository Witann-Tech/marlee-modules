from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    participant_ids = fields.Many2many(
        'res.partner',
        'sale_order_subscription_participant_rel',
        'order_id',
        'partner_id',
        string='Participantes permitidos',
        copy=True,
        help='Listado total de participantes habilitados para esta suscripción, incluyendo titular.',
    )
    subscription_has_recurring_products = fields.Boolean(
        string='Tiene productos de suscripción',
        compute='_compute_subscription_participant_capacity',
    )
    subscription_max_participants_total = fields.Integer(
        string='Cupo total de participantes',
        compute='_compute_subscription_participant_capacity',
    )

    @api.depends(
        'order_line.product_id',
        'order_line.product_uom_qty',
        'order_line.product_id.product_tmpl_id.recurring_invoice',
        'order_line.product_id.product_tmpl_id.max_participants_total',
    )
    def _compute_subscription_participant_capacity(self):
        for order in self:
            recurring_lines = order.order_line.filtered(
                lambda line: line.product_id and line.product_id.product_tmpl_id.recurring_invoice
            )
            order.subscription_has_recurring_products = bool(recurring_lines)
            order.subscription_max_participants_total = int(
                sum(
                    line.product_uom_qty * line.product_id.product_tmpl_id.max_participants_total
                    for line in recurring_lines
                )
            )

    def _ensure_subscription_owner_is_participant(self):
        for order in self:
            if not order.subscription_has_recurring_products or not order.partner_id:
                continue
            if order.partner_id in order.participant_ids:
                continue
            if order.id:
                order.with_context(skip_owner_participant_sync=True).write(
                    {'participant_ids': [Command.link(order.partner_id.id)]}
                )
            else:
                order.participant_ids = [Command.link(order.partner_id.id)]

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._ensure_subscription_owner_is_participant()
        return orders

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('skip_owner_participant_sync'):
            self._ensure_subscription_owner_is_participant()
        return res

    def copy_data(self, default=None):
        default = default or {}
        copied_data = super().copy_data(default=default)
        if 'participant_ids' in default:
            return copied_data

        for order, data in zip(self, copied_data):
            if order.participant_ids:
                data['participant_ids'] = [Command.set(order.participant_ids.ids)]
        return copied_data

    @api.onchange('partner_id', 'order_line', 'order_line.product_id', 'order_line.product_uom_qty')
    def _onchange_subscription_participants(self):
        self._ensure_subscription_owner_is_participant()

    @api.constrains('participant_ids', 'partner_id', 'order_line', 'order_line.product_uom_qty')
    def _check_subscription_participants(self):
        for order in self:
            if not order.subscription_has_recurring_products:
                continue

            max_participants = order.subscription_max_participants_total
            participants_count = len(order.participant_ids)
            if participants_count > max_participants:
                raise ValidationError(
                    _(
                        'No puedes asignar %(current)s participantes. El máximo permitido para esta suscripción es %(max)s.'
                    )
                    % {
                        'current': participants_count,
                        'max': max_participants,
                    }
                )
