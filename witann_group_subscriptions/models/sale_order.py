from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    wgs_effective_start_date = fields.Date(
        string='Inicio de vigencia (WGS)',
        copy=True,
        help='Fecha efectiva de inicio de vigencia para operación en POS y control de acceso.',
    )
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
        'order_line',
        'order_line.product_id',
        'order_line.product_id.product_tmpl_id.recurring_invoice',
        'order_line.product_id.product_tmpl_id.max_participants_total',
    )
    def _compute_subscription_participant_capacity(self):
        for order in self:
            recurring_lines, max_capacity = order._get_subscription_capacity_data()
            order.subscription_has_recurring_products = bool(recurring_lines)
            order.subscription_max_participants_total = int(max_capacity)

    def _get_subscription_line_qty(self, line):
        for field_name in ('product_uom_qty', 'quantity', 'qty'):
            if field_name in line._fields:
                return float(line[field_name] or 0.0)
        return 0.0

    def _get_subscription_recurring_lines(self):
        self.ensure_one()
        recurring_lines = self.order_line.filtered(
            lambda line: (
                line.product_id
                and line.product_id.product_tmpl_id.recurring_invoice
                and not ('display_type' in line._fields and line.display_type)
                and self._get_subscription_line_qty(line) > 0
            )
        )
        return recurring_lines

    def _get_subscription_capacity_data(self):
        self.ensure_one()
        recurring_lines = self._get_subscription_recurring_lines()
        capacity = int(
            sum(
                self._get_subscription_line_qty(line) * line.product_id.product_tmpl_id.max_participants_total
                for line in recurring_lines
            )
        )
        return recurring_lines, capacity

    def _ensure_subscription_owner_is_participant(self):
        for order in self:
            recurring_lines, _max_capacity = order._get_subscription_capacity_data()
            if not recurring_lines or not order.partner_id:
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

    @api.onchange('partner_id', 'order_line', 'order_line.product_id')
    def _onchange_subscription_participants(self):
        self._ensure_subscription_owner_is_participant()

    @api.constrains('participant_ids', 'partner_id', 'order_line')
    def _check_subscription_participants(self):
        for order in self:
            recurring_lines, max_participants = order._get_subscription_capacity_data()
            if not recurring_lines:
                continue

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
