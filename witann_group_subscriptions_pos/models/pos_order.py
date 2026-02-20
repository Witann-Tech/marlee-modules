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

        for field_name in ('recurring_invoice', 'is_subscription', 'subscription_ok', 'max_participants_total'):
            if field_name not in field_list:
                field_list.append(field_name)
        return params


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    wgs_participant_ids_json = fields.Text(string='Participantes de suscripción (POS)', copy=False)
    wgs_sale_order_id = fields.Many2one('sale.order', string='Suscripción generada', copy=False)
    wgs_subscription_plan_id = fields.Integer(string='Plan de suscripción (POS)', copy=False)
    wgs_subscription_pricing_id = fields.Integer(string='Tarifa de suscripción (POS)', copy=False)

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
    def wgs_get_recurring_price_for_pos(self, product_id, fallback=0.0, preferred_plan_id=False, preferred_pricing_id=False):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise UserError(_('No tienes permisos para consultar precios de suscripción desde Punto de Venta.'))

        product = self.env['product.product'].browse(int(product_id)).exists()
        if not product:
            raise UserError(_('El producto seleccionado no existe o no está disponible.'))

        choice = self._wgs_get_recurring_pricing_choice(
            product,
            fallback=fallback,
            preferred_plan_id=preferred_plan_id,
            preferred_pricing_id=preferred_pricing_id,
        )
        return {
            'price': float(choice.get('price') or 0.0),
            'plan_id': choice.get('plan_id') or False,
            'pricing_id': choice.get('pricing_id') or False,
        }

    @api.model
    def wgs_get_subscription_product_context_for_pos(self, product_id, fallback=0.0):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise UserError(_('No tienes permisos para consultar contexto de suscripción desde Punto de Venta.'))

        product = self.env['product.product'].browse(int(product_id)).exists()
        if not product:
            raise UserError(_('El producto seleccionado no existe o no está disponible.'))

        is_subscription_flag = bool(
            (('recurring_invoice' in product._fields) and product.recurring_invoice)
            or (('recurring_invoice' in product.product_tmpl_id._fields) and product.product_tmpl_id.recurring_invoice)
            or (('is_subscription' in product._fields) and product.is_subscription)
            or (('is_subscription' in product.product_tmpl_id._fields) and product.product_tmpl_id.is_subscription)
        )
        max_total = int(product.max_participants_total or 1)
        if max_total < 1:
            max_total = 1

        candidates = self._wgs_get_recurring_pricing_candidates(product)
        candidates.sort(key=lambda row: (row['sequence'], row.get('pricing_id') or 0))
        is_subscription = bool(is_subscription_flag or candidates)

        choice = self._wgs_get_recurring_pricing_choice(product, fallback=fallback)
        default_plan_id = choice.get('plan_id') or False
        default_pricing_id = choice.get('pricing_id') or False

        return {
            'is_subscription': is_subscription,
            'max_participants_total': max_total,
            'default_plan_id': default_plan_id,
            'default_pricing_id': default_pricing_id,
            'default_price': float(choice.get('price') or fallback or 0.0),
            'plans': [
                {
                    'plan_id': row.get('plan_id') or False,
                    'plan_name': row.get('plan_name') or _('Plan recurrente'),
                    'pricing_id': row.get('pricing_id') or False,
                    'price': float(row.get('price') or 0.0),
                    'interval_label': row.get('interval_label') or '',
                }
                for row in candidates
            ],
        }

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

        for field_name in ('wgs_subscription_plan_id', 'wgs_subscription_pricing_id'):
            value = ui_line.get(field_name)
            try:
                int_value = int(value)
            except (TypeError, ValueError):
                int_value = 0
            if int_value > 0:
                values[field_name] = int_value

        return values

    @api.model
    def _wgs_extract_ui_line_payload(self, line):
        if isinstance(line, dict):
            return line
        if isinstance(line, (list, tuple)) and len(line) >= 3 and isinstance(line[2], dict):
            return line[2]
        return {}

    @api.model
    def _process_order(self, order, draft, *args, **kwargs):
        existing_order = kwargs.get('existing_order', False)
        if args:
            existing_order = args[0]
        super_process_order = super()._process_order
        try:
            pos_order_id = super_process_order(order, draft, existing_order)
        except TypeError as error:
            # Keep compatibility with Odoo variants where _process_order only accepts (order, draft).
            if '_process_order' in str(error) and 'positional arguments' in str(error):
                pos_order_id = super_process_order(order, draft)
            else:
                raise
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

        pricing_choice = self._wgs_get_recurring_pricing_choice(
            product,
            fallback=line.price_unit,
            preferred_plan_id=line.wgs_subscription_plan_id,
            preferred_pricing_id=line.wgs_subscription_pricing_id,
        )
        recurring_price_unit = pricing_choice['price']
        recurring_plan_id = pricing_choice.get('plan_id')
        recurring_pricing_id = pricing_choice.get('pricing_id')

        sale_order_line_fields = self.env['sale.order.line']._fields
        line_values = {'product_id': product.id}
        if 'name' in sale_order_line_fields:
            line_values['name'] = line.full_product_name or product.display_name

        qty_field_name = next(
            (
                field_name
                for field_name in ('product_uom_qty', 'quantity', 'qty')
                if field_name in sale_order_line_fields
            ),
            False,
        )
        if qty_field_name:
            line_values[qty_field_name] = qty

        uom_field_name = next(
            (
                field_name
                for field_name in ('product_uom_id', 'product_uom', 'uom_id')
                if field_name in sale_order_line_fields
            ),
            False,
        )
        if uom_field_name and product.uom_id:
            line_values[uom_field_name] = product.uom_id.id

        if 'price_unit' in sale_order_line_fields:
            line_values['price_unit'] = recurring_price_unit
        if 'discount' in sale_order_line_fields:
            line_values['discount'] = line.discount

        if recurring_plan_id:
            for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
                if field_name in sale_order_line_fields:
                    line_values[field_name] = recurring_plan_id
        if recurring_pricing_id:
            for field_name in ('subscription_pricing_id', 'pricing_id', 'recurring_pricing_id'):
                if field_name in sale_order_line_fields:
                    line_values[field_name] = recurring_pricing_id

        sale_order_values = {
            'partner_id': self.partner_id.id,
            'origin': self.pos_reference or self.name,
            'client_order_ref': self.pos_reference or self.name,
            'company_id': self.company_id.id,
            'order_line': [Command.create(line_values)],
        }
        if 'pricelist_id' in self._fields and self.pricelist_id:
            sale_order_values['pricelist_id'] = self.pricelist_id.id
        if recurring_plan_id:
            for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
                if field_name in self.env['sale.order']._fields and field_name not in sale_order_values:
                    sale_order_values[field_name] = recurring_plan_id

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

    def _wgs_get_recurring_pricing_choice(self, product, fallback=0.0, preferred_plan_id=False, preferred_pricing_id=False):
        product.ensure_one()
        fallback_price = float(fallback or 0.0)

        candidates = self._wgs_get_recurring_pricing_candidates(product)

        if not candidates:
            return {
                'price': fallback_price,
                'plan_id': False,
                'pricing_id': False,
            }

        preferred_plan_id = int(preferred_plan_id or 0)
        preferred_pricing_id = int(preferred_pricing_id or 0)
        if preferred_pricing_id:
            matching = [row for row in candidates if int(row.get('pricing_id') or 0) == preferred_pricing_id]
            if matching:
                return matching[0]
        if preferred_plan_id:
            matching = [row for row in candidates if int(row.get('plan_id') or 0) == preferred_plan_id]
            if matching:
                matching.sort(key=lambda row: (row['sequence'], row.get('pricing_id') or 0))
                return matching[0]

        # Pick the first configured recurring price (ordered by sequence / id).
        candidates.sort(key=lambda row: (row['sequence'], row.get('pricing_id') or 0))
        return candidates[0]

    def _wgs_get_recurring_pricing_candidates(self, product):
        product.ensure_one()
        candidates = []
        seen_pricing_ids = set()

        for source in (product, product.product_tmpl_id):
            for field_name in ('subscription_pricing_ids', 'recurring_pricing_ids'):
                if field_name not in source._fields:
                    continue
                for pricing in source[field_name]:
                    if pricing.id in seen_pricing_ids:
                        continue
                    candidate = self._wgs_build_pricing_candidate(pricing)
                    if candidate:
                        seen_pricing_ids.add(pricing.id)
                        candidates.append(candidate)

            # Fallback: detect any relational field to sale.subscription.pricing.
            for field_name, field in source._fields.items():
                if field_name in ('subscription_pricing_ids', 'recurring_pricing_ids'):
                    continue
                if getattr(field, 'comodel_name', False) != 'sale.subscription.pricing':
                    continue
                if field.type not in ('many2one', 'one2many', 'many2many'):
                    continue
                records = source[field_name]
                for pricing in records:
                    if pricing.id in seen_pricing_ids:
                        continue
                    candidate = self._wgs_build_pricing_candidate(pricing)
                    if candidate:
                        seen_pricing_ids.add(pricing.id)
                        candidates.append(candidate)

        if not candidates:
            candidates.extend(self._wgs_search_subscription_pricing_records(product))

        return candidates

    def _wgs_build_pricing_candidate(self, pricing):
        price = self._wgs_extract_price_from_pricing(pricing)
        if price is None:
            return False
        return {
            'sequence': self._wgs_extract_pricing_sequence(pricing),
            'pricing_id': pricing.id,
            'plan_id': self._wgs_extract_plan_id_from_pricing(pricing),
            'plan_name': self._wgs_extract_plan_name_from_pricing(pricing),
            'interval_label': self._wgs_extract_plan_interval_label_from_pricing(pricing),
            'price': float(price),
        }

    def _wgs_search_subscription_pricing_records(self, product):
        pricing_model_name = 'sale.subscription.pricing'
        if pricing_model_name not in self.env.registry:
            return []

        pricing_model = self.env[pricing_model_name]
        fields_map = pricing_model._fields
        records = pricing_model.browse()

        for field_name in ('product_id', 'product_variant_id'):
            if field_name in fields_map:
                records |= pricing_model.search([(field_name, '=', product.id)])

        for field_name in ('product_template_id', 'product_tmpl_id'):
            if field_name in fields_map:
                records |= pricing_model.search([(field_name, '=', product.product_tmpl_id.id)])

        # Generic fallback for custom field names in sale.subscription.pricing.
        for field_name, field in fields_map.items():
            if field.type != 'many2one':
                continue
            comodel_name = getattr(field, 'comodel_name', False)
            if comodel_name == 'product.product':
                records |= pricing_model.search([(field_name, '=', product.id)])
            elif comodel_name == 'product.template':
                records |= pricing_model.search([(field_name, '=', product.product_tmpl_id.id)])

        seen = set()
        output = []
        for pricing in records:
            if pricing.id in seen:
                continue
            seen.add(pricing.id)
            price = self._wgs_extract_price_from_pricing(pricing)
            if price is None:
                continue
            output.append({
                'sequence': self._wgs_extract_pricing_sequence(pricing),
                'pricing_id': pricing.id,
                'plan_id': self._wgs_extract_plan_id_from_pricing(pricing),
                'plan_name': self._wgs_extract_plan_name_from_pricing(pricing),
                'interval_label': self._wgs_extract_plan_interval_label_from_pricing(pricing),
                'price': float(price),
            })
        return output

    def _wgs_extract_plan_id_from_pricing(self, pricing):
        for field_name in ('plan_id', 'subscription_plan_id', 'recurring_plan_id'):
            if field_name in pricing._fields and pricing[field_name]:
                return pricing[field_name].id
        return False

    def _wgs_extract_plan_name_from_pricing(self, pricing):
        for field_name in ('plan_id', 'subscription_plan_id', 'recurring_plan_id'):
            if field_name in pricing._fields and pricing[field_name]:
                return pricing[field_name].display_name
        return False

    def _wgs_extract_plan_interval_label_from_pricing(self, pricing):
        plan = False
        for field_name in ('plan_id', 'subscription_plan_id', 'recurring_plan_id'):
            if field_name in pricing._fields and pricing[field_name]:
                plan = pricing[field_name]
                break
        if not plan:
            return ''

        interval_value = 1
        interval_unit = 'month'
        if {'recurring_interval', 'recurring_rule_type'}.issubset(plan._fields):
            interval_value = plan.recurring_interval or 1
            interval_unit = plan.recurring_rule_type or 'month'
        elif {'billing_period_value', 'billing_period_unit'}.issubset(plan._fields):
            interval_value = plan.billing_period_value or 1
            interval_unit = plan.billing_period_unit or 'month'

        return f'{interval_value} {interval_unit}'

    def _wgs_extract_price_from_pricing(self, pricing):
        for field_name in ('fixed_price', 'price', 'recurring_price', 'price_unit'):
            if field_name not in pricing._fields:
                continue
            value = pricing[field_name]
            if value is not None:
                return float(value)
        return None

    def _wgs_extract_pricing_sequence(self, pricing):
        if 'sequence' in pricing._fields and pricing.sequence is not None:
            return int(pricing.sequence)
        if 'plan_id' in pricing._fields and pricing.plan_id and 'sequence' in pricing.plan_id._fields:
            return int(pricing.plan_id.sequence or 1000)
        if 'subscription_plan_id' in pricing._fields and pricing.subscription_plan_id and 'sequence' in pricing.subscription_plan_id._fields:
            return int(pricing.subscription_plan_id.sequence or 1000)
        return 1000

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
