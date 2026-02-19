import json
import logging

from odoo import _, api, fields, models
from odoo.fields import Command
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_product_product(self):
        params = super()._loader_params_product_product()
        search_params = params.setdefault('search_params', {})
        field_list = search_params.setdefault('fields', [])

        for field_name in ('recurring_invoice', 'max_participants_total'):
            if field_name not in field_list:
                field_list.append(field_name)
        return params


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    wgs_participant_ids_json = fields.Text(string='Participantes de suscripción (POS)', copy=False)
    wgs_sale_order_id = fields.Many2one('sale.order', string='Suscripción generada', copy=False)

    def wgs_get_participant_ids(self):
        self.ensure_one()
        raw_value = self.wgs_participant_ids_json or '[]'
        try:
            values = json.loads(raw_value)
        except (TypeError, ValueError):
            return []

        if not isinstance(values, list):
            return []

        participant_ids = []
        for value in values:
            try:
                participant_id = int(value)
            except (TypeError, ValueError):
                continue
            if participant_id > 0:
                participant_ids.append(participant_id)

        # preserve order and uniqueness
        return list(dict.fromkeys(participant_ids))


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def _order_line_fields(self, line, session_id=None):
        values = super()._order_line_fields(line, session_id=session_id)
        ui_line = self._wgs_extract_ui_line_payload(line)

        participant_ids = ui_line.get('wgs_participant_ids')
        if isinstance(participant_ids, list):
            cleaned = []
            for value in participant_ids:
                try:
                    participant_id = int(value)
                except (TypeError, ValueError):
                    continue
                if participant_id > 0:
                    cleaned.append(participant_id)
            values['wgs_participant_ids_json'] = json.dumps(list(dict.fromkeys(cleaned)))

        return values

    @api.model
    def _wgs_extract_ui_line_payload(self, line):
        if isinstance(line, dict):
            return line
        if isinstance(line, (list, tuple)) and len(line) >= 3 and isinstance(line[2], dict):
            return line[2]
        return {}

    @api.model
    def _process_order(self, order, draft, existing_order):
        pos_order_id = super()._process_order(order, draft, existing_order)
        pos_order = self.browse(pos_order_id)

        if draft:
            return pos_order_id

        pos_order._wgs_sync_subscription_sales()
        return pos_order_id

    def _wgs_sync_subscription_sales(self):
        for pos_order in self:
            if not pos_order.partner_id:
                subscription_lines = pos_order.lines.filtered(
                    lambda line: line.qty > 0 and line.product_id and line.product_id.product_tmpl_id.recurring_invoice
                )
                if subscription_lines:
                    raise UserError(
                        _('Debes seleccionar un cliente para vender productos de suscripción desde Punto de Venta.')
                    )

            # 1) Create subscription sales for normal/positive subscription lines.
            for line in pos_order.lines.filtered(
                lambda item: item.qty > 0 and item.product_id and item.product_id.product_tmpl_id.recurring_invoice
            ):
                if line.wgs_sale_order_id:
                    continue
                sale_order = pos_order._wgs_create_subscription_sale_order_from_line(line)
                line.wgs_sale_order_id = sale_order.id

            # 2) Cancel subscription sale orders when POS line is a refund.
            for line in pos_order.lines.filtered(
                lambda item: item.qty < 0 and item.product_id and item.product_id.product_tmpl_id.recurring_invoice
            ):
                pos_order._wgs_cancel_subscription_from_refund_line(line)

    def _wgs_create_subscription_sale_order_from_line(self, line):
        self.ensure_one()

        product = line.product_id
        qty = abs(line.qty)
        max_total = int((product.max_participants_total or 1) * qty)
        if max_total < 1:
            max_total = 1

        participant_ids = line.wgs_get_participant_ids()
        if self.partner_id.id not in participant_ids:
            participant_ids.insert(0, self.partner_id.id)

        participant_ids = list(dict.fromkeys(participant_ids))
        if len(participant_ids) > max_total:
            raise UserError(
                _(
                    'No puedes asignar %(current)s participantes para %(product)s. El máximo permitido es %(max)s.'
                )
                % {
                    'current': len(participant_ids),
                    'product': product.display_name,
                    'max': max_total,
                }
            )

        sale_order_values = {
            'partner_id': self.partner_id.id,
            'origin': self.pos_reference or self.name,
            'client_order_ref': self.pos_reference or self.name,
            'company_id': self.company_id.id,
            'order_line': [
                Command.create(
                    {
                        'product_id': product.id,
                        'name': line.full_product_name or product.display_name,
                        'product_uom_qty': qty,
                        'product_uom': product.uom_id.id,
                        'price_unit': line.price_unit,
                        'discount': line.discount,
                    }
                )
            ],
        }

        sale_order = self.env['sale.order'].create(sale_order_values)
        sale_order.write({'participant_ids': [Command.set(participant_ids)]})

        # Confirm immediately: POS payment is considered the paid period trigger.
        sale_order.action_confirm()

        _logger.info(
            'Created sale subscription order %s from POS order %s line %s',
            sale_order.name,
            self.pos_reference,
            line.id,
        )
        return sale_order

    def _wgs_cancel_subscription_from_refund_line(self, line):
        self.ensure_one()

        original_line = None
        if 'refunded_orderline_id' in line._fields:
            original_line = line.refunded_orderline_id

        if not original_line or not original_line.wgs_sale_order_id:
            return

        sale_order = original_line.wgs_sale_order_id
        if sale_order.state == 'cancel':
            line.wgs_sale_order_id = sale_order.id
            return

        sale_order.action_cancel()
        line.wgs_sale_order_id = sale_order.id

        _logger.info(
            'Cancelled sale subscription order %s from POS refund order %s line %s',
            sale_order.name,
            self.pos_reference,
            line.id,
        )

    def action_pos_order_cancel(self):
        super_method = getattr(super(), 'action_pos_order_cancel', None)
        result = super_method() if super_method else True
        for order in self:
            sale_orders = order.lines.mapped('wgs_sale_order_id').filtered(lambda so: so and so.state != 'cancel')
            for sale_order in sale_orders:
                sale_order.action_cancel()
        return result
