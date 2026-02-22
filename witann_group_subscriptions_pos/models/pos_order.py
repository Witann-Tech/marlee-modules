import json
import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta

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

        for field_name in (
            'recurring_invoice',
            'is_subscription',
            'subscription_ok',
            'max_participants_total',
        ):
            if field_name not in field_list:
                field_list.append(field_name)
        return params


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    wgs_participant_ids_json = fields.Text(string='Participantes de suscripción (POS)', copy=False)
    wgs_sale_order_id = fields.Many2one('sale.order', string='Suscripción generada', copy=False)
    wgs_subscription_plan_id = fields.Integer(string='Plan de suscripción (POS)', copy=False)
    wgs_subscription_pricing_id = fields.Integer(string='Tarifa de suscripción (POS)', copy=False)
    wgs_subscription_start_date = fields.Date(string='Fecha inicio de suscripción (POS)', copy=False)
    wgs_subscription_end_date = fields.Date(string='Fecha fin de suscripción (POS)', copy=False)

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

    def wgs_get_subscription_end_date(self):
        self.ensure_one()
        if not self.wgs_subscription_end_date:
            return False
        return fields.Date.to_date(self.wgs_subscription_end_date)

    def wgs_get_subscription_start_date(self):
        self.ensure_one()
        if not self.wgs_subscription_start_date:
            return False
        return fields.Date.to_date(self.wgs_subscription_start_date)


class PosOrder(models.Model):
    _inherit = 'pos.order'
    _WGS_INVALID_SUBSCRIPTION_STATE_TOKENS = (
        'cancel',
        'churn',
        'close',
        'draft',
        'pause',
        'upsell',
    )

    @api.model
    def _wgs_is_subscription_buffer_ready(self):
        model_name = 'wgs.pos.subscription.buffer'
        if model_name not in self.env.registry:
            return False

        # Avoid hard failures when code is deployed before module upgrade creates the SQL table.
        table_name = self.env[model_name]._table
        try:
            self.env.cr.execute("SELECT to_regclass(%s)", (table_name,))
            row = self.env.cr.fetchone()
        except Exception as error:
            _logger.warning(
                'WGS POS: subscription buffer readiness check failed for table %s (%s)',
                table_name,
                error,
            )
            return False
        return bool(row and row[0])

    @api.model
    def wgs_stage_subscription_config_for_uuid(self, order_uuid, configs):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise UserError(_('No tienes permisos para guardar configuración de suscripción desde Punto de Venta.'))

        order_uuid = (order_uuid or '').strip()
        if not order_uuid:
            return {'ok': False, 'reason': 'missing_uuid'}

        if not isinstance(configs, list):
            configs = []
        payload_json = json.dumps(configs)
        if not self._wgs_is_subscription_buffer_ready():
            _logger.warning(
                'WGS POS: subscription buffer table is not ready yet. Skipping stage for uuid=%s',
                order_uuid,
            )
            return {'ok': False, 'reason': 'buffer_not_ready'}

        try:
            buffer_model = self.env['wgs.pos.subscription.buffer'].sudo()
            existing = buffer_model.search([('order_uuid', '=', order_uuid)], limit=1, order='id desc')
            if existing:
                existing.write({'payload_json': payload_json})
            else:
                buffer_model.create({'order_uuid': order_uuid, 'payload_json': payload_json})
        except Exception as error:
            _logger.warning(
                'WGS POS: could not stage subscription buffer for uuid=%s (%s)',
                order_uuid,
                error,
            )
            return {'ok': False, 'reason': 'buffer_error'}
        return {'ok': True}

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
        default_min_term_periods = max(0, int(choice.get('min_term_periods') or 0))

        return {
            'is_subscription': is_subscription,
            'max_participants_total': max_total,
            'min_term_periods': default_min_term_periods,
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
                    'interval_value': int(row.get('interval_value') or 1),
                    'interval_unit': row.get('interval_unit') or 'month',
                    'min_term_periods': max(0, int(row.get('min_term_periods') or 0)),
                }
                for row in candidates
            ],
        }

    @api.model
    def _order_line_fields(self, line, session_id=None):
        values = super()._order_line_fields(line, session_id=session_id)
        ui_line = self._wgs_extract_ui_line_payload(line)
        config_payload = self._wgs_extract_subscription_config_payload(ui_line)

        participant_ids = config_payload.get('participant_ids')
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
            if field_name == 'wgs_subscription_plan_id':
                value = config_payload.get('plan_id')
            else:
                value = config_payload.get('pricing_id')
            try:
                int_value = int(value)
            except (TypeError, ValueError):
                int_value = 0
            if int_value > 0:
                values[field_name] = int_value

        raw_end_date = config_payload.get('end_date')
        if raw_end_date:
            end_date = fields.Date.to_date(raw_end_date)
            if end_date:
                values['wgs_subscription_end_date'] = end_date
        raw_start_date = config_payload.get('start_date')
        if raw_start_date:
            start_date = fields.Date.to_date(raw_start_date)
            if start_date:
                values['wgs_subscription_start_date'] = start_date

        return values

    @api.model
    def _wgs_extract_ui_line_payload(self, line):
        payload = {}

        def _collect(node, depth=0):
            if depth > 5:
                return
            if isinstance(node, dict):
                payload.update(node)
                for value in node.values():
                    _collect(value, depth + 1)
            elif isinstance(node, (list, tuple)):
                for value in node:
                    _collect(value, depth + 1)

        _collect(line)
        return payload

    @api.model
    def _wgs_extract_subscription_config_payload(self, ui_line):
        data = {
            'participant_ids': [],
            'plan_id': False,
            'pricing_id': False,
            'start_date': False,
            'end_date': False,
        }
        if not isinstance(ui_line, dict):
            return data

        raw_config = ui_line.get('wgs_subscription_config')
        if isinstance(raw_config, str):
            try:
                raw_config = json.loads(raw_config)
            except (TypeError, ValueError):
                raw_config = {}
        if not isinstance(raw_config, dict):
            raw_config = {}

        participant_raw = (
            ui_line.get('wgs_participant_ids')
            or ui_line.get('wgsParticipantIds')
            or raw_config.get('participant_ids')
            or raw_config.get('participantIds')
            or []
        )
        if isinstance(participant_raw, str):
            try:
                participant_raw = json.loads(participant_raw)
            except (TypeError, ValueError):
                participant_raw = []
        if isinstance(participant_raw, list):
            data['participant_ids'] = participant_raw

        data['plan_id'] = (
            ui_line.get('wgs_subscription_plan_id')
            or ui_line.get('wgsSubscriptionPlanId')
            or raw_config.get('plan_id')
            or raw_config.get('planId')
            or False
        )
        data['pricing_id'] = (
            ui_line.get('wgs_subscription_pricing_id')
            or ui_line.get('wgsSubscriptionPricingId')
            or raw_config.get('pricing_id')
            or raw_config.get('pricingId')
            or False
        )
        data['end_date'] = (
            ui_line.get('wgs_subscription_end_date')
            or ui_line.get('wgsSubscriptionEndDate')
            or raw_config.get('end_date')
            or raw_config.get('endDate')
            or False
        )
        data['start_date'] = (
            ui_line.get('wgs_subscription_start_date')
            or ui_line.get('wgsSubscriptionStartDate')
            or raw_config.get('start_date')
            or raw_config.get('startDate')
            or False
        )

        return data

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

        order_uuid = self._wgs_extract_order_uuid(order)
        ui_configs = pos_order._wgs_extract_ui_subscription_line_configs(order)
        if not ui_configs and order_uuid:
            ui_configs = pos_order._wgs_get_buffered_subscription_configs(order_uuid)

        if ui_configs:
            pos_order._wgs_apply_subscription_line_configs(ui_configs)
        else:
            pos_order._wgs_apply_ui_subscription_line_config(order)
        pos_order._wgs_sync_subscription_sales()
        return pos_order_id

    @api.model
    def _wgs_extract_order_uuid(self, ui_order):
        if not isinstance(ui_order, dict):
            return False
        for key in ('uuid', 'uid', 'order_uuid', 'orderUid'):
            value = ui_order.get(key)
            if value:
                return str(value).strip()
        return False

    def _wgs_get_buffered_subscription_configs(self, order_uuid):
        order_uuid = (order_uuid or '').strip()
        if not order_uuid:
            return []
        if not self._wgs_is_subscription_buffer_ready():
            return []

        try:
            buffer_model = self.env['wgs.pos.subscription.buffer'].sudo()
            buffer_record = buffer_model.search([('order_uuid', '=', order_uuid)], limit=1, order='id desc')
            if not buffer_record:
                return []
            try:
                payload = json.loads(buffer_record.payload_json or '[]')
            except (TypeError, ValueError):
                payload = []
            buffer_record.unlink()
        except Exception as error:
            _logger.warning(
                'WGS POS: could not recover subscription buffer for uuid=%s (%s)',
                order_uuid,
                error,
            )
            return []

        if not isinstance(payload, list):
            return []
        _logger.info('WGS POS: recovered %s buffered subscription configs for uuid=%s', len(payload), order_uuid)
        return payload

    def _wgs_apply_ui_subscription_line_config(self, ui_order):
        self.ensure_one()
        ui_configs = self._wgs_extract_ui_subscription_line_configs(ui_order)
        if not ui_configs:
            return
        self._wgs_apply_subscription_line_configs(ui_configs)

    def _wgs_apply_subscription_line_configs(self, ui_configs):
        self.ensure_one()
        if not ui_configs:
            return

        candidate_lines = self.lines.filtered(
            lambda line: line.qty > 0 and line.product_id and line.product_id.product_tmpl_id.recurring_invoice
        ).sorted(key=lambda line: line.id)
        if not candidate_lines:
            return

        unmatched_lines = candidate_lines
        for config in ui_configs:
            target_line = self._wgs_match_pos_line_for_ui_config(unmatched_lines, config)
            if not target_line:
                continue
            write_values = {}

            participant_ids = config.get('participant_ids') or []
            if isinstance(participant_ids, list):
                cleaned = []
                for value in participant_ids:
                    try:
                        participant_id = int(value)
                    except (TypeError, ValueError):
                        continue
                    if participant_id > 0:
                        cleaned.append(participant_id)
                if cleaned:
                    write_values['wgs_participant_ids_json'] = json.dumps(list(dict.fromkeys(cleaned)))

            for field_name, key_name in (
                ('wgs_subscription_plan_id', 'plan_id'),
                ('wgs_subscription_pricing_id', 'pricing_id'),
            ):
                try:
                    numeric = int(config.get(key_name) or 0)
                except (TypeError, ValueError):
                    numeric = 0
                if numeric > 0:
                    write_values[field_name] = numeric

            raw_end_date = config.get('end_date')
            if raw_end_date:
                end_date = fields.Date.to_date(raw_end_date)
                if end_date:
                    write_values['wgs_subscription_end_date'] = end_date
            raw_start_date = config.get('start_date')
            if raw_start_date:
                start_date = fields.Date.to_date(raw_start_date)
                if start_date:
                    write_values['wgs_subscription_start_date'] = start_date

            if write_values:
                target_line.write(write_values)
                _logger.info(
                    'WGS POS: applied UI config to pos.order.line %s -> %s',
                    target_line.id,
                    write_values,
                )
            unmatched_lines -= target_line

    @api.model
    def _wgs_extract_ui_subscription_line_configs(self, ui_order):
        output = []
        if not isinstance(ui_order, dict):
            return output

        raw_root_configs = ui_order.get('wgs_subscription_configs')
        if isinstance(raw_root_configs, str):
            try:
                raw_root_configs = json.loads(raw_root_configs)
            except (TypeError, ValueError):
                raw_root_configs = []
        if isinstance(raw_root_configs, list):
            for item in raw_root_configs:
                if not isinstance(item, dict):
                    continue
                config = self._wgs_extract_subscription_config_payload(item)
                config['product_id'] = self._wgs_to_int(item.get('product_id') or item.get('productId'))
                config['quantity'] = self._wgs_to_float(item.get('quantity') or item.get('qty'))
                output.append(config)
            if output:
                _logger.info('WGS POS: extracted %s root subscription configs from UI order.', len(output))
                return output

        raw_lines = ui_order.get('lines')
        if not isinstance(raw_lines, list):
            return output

        for raw_line in raw_lines:
            payload = self._wgs_find_best_payload_dict(raw_line)
            if not isinstance(payload, dict):
                continue
            config = self._wgs_extract_subscription_config_payload(payload)
            if not (
                config.get('participant_ids')
                or config.get('plan_id')
                or config.get('pricing_id')
                or config.get('start_date')
                or config.get('end_date')
            ):
                continue

            config['product_id'] = self._wgs_to_int(payload.get('product_id') or payload.get('productId'))
            config['quantity'] = self._wgs_to_float(payload.get('qty') or payload.get('quantity') or payload.get('qty_ordered'))
            output.append(config)
        return output

    @api.model
    def _wgs_to_int(self, value):
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @api.model
    def _wgs_to_float(self, value):
        try:
            return abs(float(value or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @api.model
    def _wgs_find_best_payload_dict(self, raw_line):
        best = {}

        def _walk(node, depth=0):
            nonlocal best
            if depth > 6:
                return
            if isinstance(node, dict):
                score = 0
                if any(key in node for key in ('product_id', 'productId')):
                    score += 3
                if any(key in node for key in ('qty', 'quantity', 'qty_ordered')):
                    score += 2
                if any(key in node for key in ('wgs_subscription_config', 'wgs_participant_ids', 'wgsParticipantIds')):
                    score += 4
                if score > best.get('__score__', -1):
                    best = dict(node)
                    best['__score__'] = score
                for value in node.values():
                    _walk(value, depth + 1)
            elif isinstance(node, (list, tuple)):
                for value in node:
                    _walk(value, depth + 1)

        _walk(raw_line)
        best.pop('__score__', None)
        return best

    @api.model
    def _wgs_match_pos_line_for_ui_config(self, lines, config):
        if not lines:
            return self.env['pos.order.line']

        product_id = int(config.get('product_id') or 0)
        quantity = float(config.get('quantity') or 0.0)
        candidates = lines
        if product_id > 0:
            filtered = lines.filtered(lambda line: line.product_id.id == product_id)
            if filtered:
                candidates = filtered
        if quantity > 0:
            filtered = candidates.filtered(lambda line: abs(abs(line.qty) - quantity) < 0.0001)
            if filtered:
                candidates = filtered
        return candidates[:1]

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

        if recurring_pricing_id and not recurring_plan_id:
            pricing_record = self.env['sale.subscription.pricing'].browse(int(recurring_pricing_id)).exists()
            if pricing_record:
                recurring_plan_id = self._wgs_extract_plan_id_from_pricing(pricing_record)
        if not recurring_plan_id:
            recurring_plan_id = self._wgs_extract_plan_id_from_product(product)
        if not recurring_plan_id:
            _logger.warning(
                'WGS POS: No recurring plan resolved for product %s (id=%s). pricing_id=%s choice=%s',
                product.display_name,
                product.id,
                recurring_pricing_id,
                pricing_choice,
            )
        plan_record = self._wgs_resolve_plan_record(
            product=product,
            plan_id=recurring_plan_id,
            pricing_id=recurring_pricing_id,
        )
        today = fields.Date.context_today(self)
        subscription_start_date = line.wgs_get_subscription_start_date() or today
        subscription_end_date = line.wgs_get_subscription_end_date()
        minimum_term_periods = max(0, int(pricing_choice.get('min_term_periods') or 0))
        if plan_record:
            minimum_term_periods = self._wgs_get_plan_min_term_periods(plan_record)
        sale_start_date = subscription_start_date
        if subscription_start_date < today:
            raise UserError(
                _(
                    'La fecha de inicio no puede ser anterior a %(date)s.'
                )
                % {'date': fields.Date.to_string(today)}
            )
        required_periods = max(1, minimum_term_periods)
        if subscription_end_date or minimum_term_periods > 0:
            if not plan_record:
                raise UserError(
                    _('No se pudo validar la fecha de finalización porque el plan recurrente no está definido.')
                )
            min_threshold_date = self._wgs_get_plan_min_end_threshold(
                plan_record,
                sale_start_date,
                periods_count=required_periods,
            )
            if not subscription_end_date and minimum_term_periods > 0:
                subscription_end_date = min_threshold_date
            elif subscription_end_date and subscription_end_date < min_threshold_date:
                raise UserError(
                    _(
                        'La fecha de finalización debe ser igual o posterior a %(date)s para el plan %(plan)s '
                        '(plazo mínimo aplicado: %(periods)s periodos).'
                    )
                    % {
                        'date': fields.Date.to_string(min_threshold_date),
                        'plan': plan_record.display_name,
                        'periods': required_periods,
                    }
                )

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
            self._wgs_assign_many2one_value(
                values=line_values,
                fields_map=sale_order_line_fields,
                value_id=recurring_plan_id,
                preferred_field_names=('subscription_plan_id', 'plan_id', 'recurring_plan_id'),
                comodel_checker=self._wgs_is_plan_model_name,
            )
        if recurring_pricing_id:
            for field_name in ('subscription_pricing_id', 'pricing_id', 'recurring_pricing_id'):
                if field_name in sale_order_line_fields:
                    line_values[field_name] = recurring_pricing_id
            self._wgs_assign_many2one_value(
                values=line_values,
                fields_map=sale_order_line_fields,
                value_id=recurring_pricing_id,
                preferred_field_names=('subscription_pricing_id', 'pricing_id', 'recurring_pricing_id'),
                comodel_checker=self._wgs_is_pricing_model_name,
            )

        contract_date = fields.Date.context_today(self)
        upsell_source_order = self._wgs_find_partner_active_subscription_for_upsell()
        if upsell_source_order:
            upsell_order = self._wgs_create_subscription_upsell_sale_order_from_line(
                source_order=upsell_source_order,
                line_values=dict(line_values),
            )
            sale_order_line = upsell_order.order_line.filtered(lambda so_line: so_line.product_id == product)[:1]
            if not sale_order_line:
                sale_order_line = upsell_order.order_line[:1]
            self._wgs_link_pos_and_sale_records(
                pos_line=line,
                sale_order=upsell_order,
                sale_order_line=sale_order_line,
            )

            if upsell_order.state in ('draft', 'sent'):
                upsell_order.action_confirm()

            # On upsell we keep original contract/start dates; only sync participant and optional end date.
            self._wgs_sync_subscription_metadata(
                sale_order=upsell_order,
                participant_ids=participant_ids,
                contract_date=False,
                subscription_start_date=False,
                subscription_end_date=subscription_end_date,
                next_billing_date=False,
            )

            _logger.info(
                'Created subscription upsell order %s from POS order %s line %s (source=%s)',
                upsell_order.name,
                self.pos_reference,
                line.id,
                upsell_source_order.name,
            )
            return upsell_order

        sale_order_fields = self.env['sale.order']._fields
        sale_order_values = {
            'partner_id': self.partner_id.id,
            'origin': self.pos_reference or self.name,
            'client_order_ref': self.pos_reference or self.name,
            'company_id': self.company_id.id,
            'order_line': [Command.create(line_values)],
        }
        if 'date_order' in sale_order_fields:
            sale_order_values['date_order'] = self._wgs_convert_date_for_field_value(
                contract_date,
                sale_order_fields.get('date_order'),
            )
        self._wgs_assign_date_field(
            values=sale_order_values,
            fields_map=sale_order_fields,
            date_value=contract_date,
            preferred_field_names=('first_contract_date', 'contract_date', 'date_contract'),
        )
        if 'pricelist_id' in self._fields and self.pricelist_id:
            sale_order_values['pricelist_id'] = self.pricelist_id.id
        self._wgs_assign_date_field(
            values=sale_order_values,
            fields_map=sale_order_fields,
            date_value=sale_start_date,
            preferred_field_names=('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date'),
        )
        if subscription_end_date:
            self._wgs_assign_date_field(
                values=sale_order_values,
                fields_map=sale_order_fields,
                date_value=subscription_end_date,
                preferred_field_names=('end_date', 'date_end', 'subscription_end_date', 'recurring_end_date'),
            )
        if recurring_plan_id:
            for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
                if field_name in sale_order_fields and field_name not in sale_order_values:
                    sale_order_values[field_name] = recurring_plan_id
            self._wgs_assign_many2one_value(
                values=sale_order_values,
                fields_map=sale_order_fields,
                value_id=recurring_plan_id,
                preferred_field_names=('subscription_plan_id', 'plan_id', 'recurring_plan_id'),
                comodel_checker=self._wgs_is_plan_model_name,
            )

        next_billing_date = False
        if plan_record:
            next_billing_date = self._wgs_get_plan_min_end_threshold(plan_record, sale_start_date)

        sale_order = self.env['sale.order'].create(sale_order_values)
        if 'participant_ids' in sale_order._fields:
            sale_order.write({'participant_ids': [Command.set(participant_ids)]})
            _logger.info(
                'WGS POS: participant_ids synced on sale order %s -> %s',
                sale_order.name,
                participant_ids,
            )

        sale_order_line = sale_order.order_line.filtered(lambda so_line: so_line.product_id == product)[:1]
        if not sale_order_line:
            sale_order_line = sale_order.order_line[:1]
        self._wgs_link_pos_and_sale_records(
            pos_line=line,
            sale_order=sale_order,
            sale_order_line=sale_order_line,
        )

        # Confirm immediately: POS payment is considered the paid period trigger.
        sale_order.action_confirm()
        self._wgs_sync_subscription_metadata(
            sale_order=sale_order,
            participant_ids=participant_ids,
            contract_date=contract_date,
            subscription_start_date=subscription_start_date,
            subscription_end_date=subscription_end_date,
            next_billing_date=next_billing_date,
        )

        _logger.info(
            'Created sale subscription order %s from POS order %s line %s',
            sale_order.name,
            self.pos_reference,
            line.id,
        )
        return sale_order

    def _wgs_find_partner_active_subscription_for_upsell(self):
        self.ensure_one()
        if not self.partner_id:
            return False

        domain = [
            ('partner_id', '=', self.partner_id.id),
            ('state', 'in', ['sale', 'done']),
        ]
        if 'company_id' in self._fields and self.company_id:
            domain.append(('company_id', '=', self.company_id.id))

        candidates = self.env['sale.order'].search(domain, order='id desc', limit=25)
        candidates = candidates.filtered(
            lambda order: (
                bool(order.order_line.filtered(
                    lambda so_line: so_line.product_id and so_line.product_id.product_tmpl_id.recurring_invoice
                ))
                and self._wgs_is_subscription_order_active_for_upsell(order)
            )
        )
        if not candidates:
            return False

        if len(candidates) > 1:
            _logger.warning(
                'WGS POS: multiple active subscriptions for partner %s. Using most recent %s',
                self.partner_id.id,
                candidates[0].name,
            )
        return candidates[0]

    def _wgs_is_subscription_order_active_for_upsell(self, sale_order):
        sale_order.ensure_one()
        if 'subscription_state' not in sale_order._fields:
            return True
        state_value = (sale_order.subscription_state or '').lower()
        if not state_value:
            return True
        return not any(token in state_value for token in self._WGS_INVALID_SUBSCRIPTION_STATE_TOKENS)

    def _wgs_create_subscription_upsell_sale_order_from_line(self, source_order, line_values):
        self.ensure_one()
        source_order.ensure_one()

        upsell_order = self._wgs_get_or_create_subscription_upsell_order(source_order)
        if not upsell_order:
            raise UserError(
                _(
                    'No se pudo generar una cotización de Upsell para la suscripción %(subscription)s.'
                ) % {'subscription': source_order.display_name}
            )
        if upsell_order.state not in ('draft', 'sent'):
            raise UserError(
                _(
                    'La cotización de Upsell %(order)s no está en borrador.'
                ) % {'order': upsell_order.display_name}
            )

        write_values = {}
        if 'origin' in upsell_order._fields:
            write_values['origin'] = self.pos_reference or self.name
        if 'client_order_ref' in upsell_order._fields:
            write_values['client_order_ref'] = self.pos_reference or self.name
        if 'pricelist_id' in self._fields and self.pricelist_id and 'pricelist_id' in upsell_order._fields:
            write_values['pricelist_id'] = self.pricelist_id.id
        if write_values:
            upsell_order.write(write_values)

        # Replace default lines generated by upsell action with POS-selected target package.
        if upsell_order.order_line:
            upsell_order.order_line.unlink()
        upsell_order.write({'order_line': [Command.create(line_values)]})

        return upsell_order

    def _wgs_get_or_create_subscription_upsell_order(self, source_order):
        source_order.ensure_one()

        method_names = (
            'action_upsell',
            'action_subscription_upsell',
            'action_subscription_create_upsell',
        )
        for method_name in method_names:
            method = getattr(source_order, method_name, None)
            if not callable(method):
                continue
            try:
                result = method()
            except Exception as error:
                _logger.warning(
                    'WGS POS: upsell method %s failed on %s (%s)',
                    method_name,
                    source_order.name,
                    error,
                )
                continue

            upsell_order = self._wgs_extract_sale_order_from_upsell_result(result, source_order)
            if upsell_order:
                return upsell_order

        return self._wgs_find_recent_subscription_upsell_order(source_order)

    def _wgs_extract_sale_order_from_upsell_result(self, result, source_order):
        if not result:
            return self.env['sale.order']

        if isinstance(result, models.BaseModel):
            if result._name == 'sale.order':
                return result.exists()[:1]
            return self.env['sale.order']

        if isinstance(result, int):
            return self.env['sale.order'].browse(int(result)).exists()[:1]

        if isinstance(result, dict):
            res_model = result.get('res_model')
            res_id = result.get('res_id')
            if res_model == 'sale.order' and res_id:
                return self.env['sale.order'].browse(int(res_id)).exists()[:1]

            context = result.get('context') or {}
            default_res_id = context.get('default_subscription_id') or context.get('default_origin_order_id')
            if default_res_id and int(default_res_id) != source_order.id:
                candidate = self.env['sale.order'].browse(int(default_res_id)).exists()
                if candidate:
                    return candidate[:1]

        return self.env['sale.order']

    def _wgs_find_recent_subscription_upsell_order(self, source_order):
        source_order.ensure_one()
        sale_order_model = self.env['sale.order']

        preferred_relation_fields = (
            'subscription_id',
            'origin_order_id',
            'note_order',
        )
        for field_name in preferred_relation_fields:
            field = sale_order_model._fields.get(field_name)
            if not field or field.type != 'many2one' or getattr(field, 'comodel_name', '') != 'sale.order':
                continue
            upsell_order = sale_order_model.search(
                [
                    (field_name, '=', source_order.id),
                    ('state', 'in', ['draft', 'sent']),
                ],
                order='id desc',
                limit=1,
            )
            if upsell_order:
                return upsell_order

        for field_name, field in sale_order_model._fields.items():
            if field.type != 'many2one' or getattr(field, 'comodel_name', '') != 'sale.order':
                continue
            normalized_name = (field_name or '').lower()
            if not any(token in normalized_name for token in ('subscription', 'origin', 'upsell', 'note')):
                continue
            upsell_order = sale_order_model.search(
                [
                    (field_name, '=', source_order.id),
                    ('state', 'in', ['draft', 'sent']),
                ],
                order='id desc',
                limit=1,
            )
            if upsell_order:
                return upsell_order

        return sale_order_model.browse()

    def _wgs_link_pos_and_sale_records(self, pos_line, sale_order, sale_order_line=False):
        self.ensure_one()
        if not pos_line or not sale_order:
            return

        pos_line_values = {}
        self._wgs_assign_many2one_by_model(
            values=pos_line_values,
            fields_map=pos_line._fields,
            value_id=sale_order.id,
            model_name='sale.order',
            preferred_field_names=('sale_order_id', 'sale_order_origin_id', 'origin_sale_order_id'),
            required_name_tokens=('sale', 'order'),
        )
        if sale_order_line:
            self._wgs_assign_many2one_by_model(
                values=pos_line_values,
                fields_map=pos_line._fields,
                value_id=sale_order_line.id,
                model_name='sale.order.line',
                preferred_field_names=('sale_order_line_id', 'sale_order_origin_id', 'origin_sale_order_line_id'),
                required_name_tokens=('sale', 'line'),
            )
        if pos_line_values:
            pos_line.write(pos_line_values)

        sale_order_values = {}
        self._wgs_assign_many2one_by_model(
            values=sale_order_values,
            fields_map=sale_order._fields,
            value_id=self.id,
            model_name='pos.order',
            preferred_field_names=('pos_order_id', 'origin_pos_order_id'),
            required_name_tokens=('pos', 'order'),
        )
        if sale_order_values:
            sale_order.write(sale_order_values)

        if pos_line_values or sale_order_values:
            _logger.info(
                'WGS POS: linked POS/Sale records for pos.order %s line %s and sale.order %s line %s',
                self.pos_reference,
                pos_line.id,
                sale_order.name,
                sale_order_line.id if sale_order_line else False,
            )

    def _wgs_sync_subscription_metadata(
        self,
        sale_order,
        participant_ids,
        contract_date=False,
        subscription_start_date=False,
        subscription_end_date=False,
        next_billing_date=False,
    ):
        target_orders = self._wgs_get_subscription_orders_from_base(sale_order)
        for target_order in target_orders:
            values = {}
            participant_field = self._wgs_find_partner_multi_field(target_order)
            if participant_field:
                values[participant_field] = [Command.set(participant_ids)]
            if contract_date:
                contract_field = self._wgs_find_subscription_contract_date_field(target_order)
                if contract_field:
                    values[contract_field] = self._wgs_convert_date_for_field_value(
                        contract_date,
                        target_order._fields.get(contract_field),
                    )
                if 'date_order' in target_order._fields and 'date_order' not in values:
                    values['date_order'] = self._wgs_convert_date_for_field_value(
                        contract_date,
                        target_order._fields.get('date_order'),
                    )
            if subscription_start_date:
                start_field = self._wgs_find_subscription_start_date_field(target_order)
                if start_field:
                    values[start_field] = subscription_start_date
            if subscription_end_date:
                end_field = self._wgs_find_subscription_end_date_field(target_order)
                if end_field:
                    values[end_field] = subscription_end_date
            if next_billing_date:
                next_field = self._wgs_find_subscription_next_invoice_date_field(target_order)
                if next_field:
                    values[next_field] = next_billing_date
            if values:
                target_order.write(values)
                _logger.info(
                    'WGS POS: synced metadata on subscription order %s (participants=%s contract_date=%s start_date=%s end_date=%s next=%s)',
                    target_order.name,
                    participant_ids,
                    contract_date or False,
                    subscription_start_date or False,
                    subscription_end_date or False,
                    next_billing_date or False,
                )

    def _wgs_get_subscription_orders_from_base(self, sale_order):
        orders = sale_order
        fields_map = sale_order._fields

        for field_name, field in fields_map.items():
            if getattr(field, 'comodel_name', '') != 'sale.order':
                continue
            normalized_name = (field_name or '').lower()
            if 'subscription' not in normalized_name and 'recurr' not in normalized_name:
                continue
            value = sale_order[field_name]
            if field.type == 'many2one' and value:
                orders |= value
            elif field.type in ('one2many', 'many2many'):
                orders |= value

        recurring_orders = orders.filtered(
            lambda order: bool(
                order.order_line.filtered(
                    lambda line: line.product_id and line.product_id.product_tmpl_id.recurring_invoice
                )
            )
        )
        return recurring_orders or sale_order

    def _wgs_find_partner_multi_field(self, sale_order):
        fields_map = sale_order._fields
        field = fields_map.get('participant_ids')
        if field and field.type in ('many2many', 'one2many') and getattr(field, 'comodel_name', '') == 'res.partner':
            return 'participant_ids'

        for field_name, field in fields_map.items():
            if field.type not in ('many2many', 'one2many'):
                continue
            if getattr(field, 'comodel_name', '') != 'res.partner':
                continue
            normalized_name = (field_name or '').lower()
            if any(token in normalized_name for token in ('participant', 'member', 'attendee')):
                return field_name
        return False

    def _wgs_convert_date_for_field_value(self, date_value, field):
        date_value = fields.Date.to_date(date_value)
        if not date_value:
            return False
        if field and field.type == 'datetime':
            return fields.Datetime.to_datetime(date_value)
        return date_value

    def _wgs_find_subscription_end_date_field(self, sale_order):
        fields_map = sale_order._fields
        preferred = ('end_date', 'date_end', 'subscription_end_date', 'recurring_end_date')
        for field_name in preferred:
            field = fields_map.get(field_name)
            if field and field.type in ('date', 'datetime'):
                return field_name

        for field_name, field in fields_map.items():
            if field.type not in ('date', 'datetime'):
                continue
            normalized_name = (field_name or '').lower()
            if any(token in normalized_name for token in ('end', 'until', 'close')) and any(
                token in normalized_name for token in ('subscription', 'recurr', 'period')
            ):
                return field_name
        return False

    def _wgs_find_subscription_start_date_field(self, sale_order):
        fields_map = sale_order._fields
        preferred = ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date', 'recurring_start_date')
        for field_name in preferred:
            field = fields_map.get(field_name)
            if field and field.type in ('date', 'datetime'):
                return field_name

        for field_name, field in fields_map.items():
            if field.type not in ('date', 'datetime'):
                continue
            normalized_name = (field_name or '').lower()
            if any(token in normalized_name for token in ('start', 'begin', 'from')) and any(
                token in normalized_name for token in ('subscription', 'recurr', 'period')
            ):
                return field_name
        return False

    def _wgs_find_subscription_contract_date_field(self, sale_order):
        fields_map = sale_order._fields
        preferred = ('first_contract_date', 'contract_date', 'date_contract')
        for field_name in preferred:
            field = fields_map.get(field_name)
            if field and field.type in ('date', 'datetime'):
                return field_name

        for field_name, field in fields_map.items():
            if field.type not in ('date', 'datetime'):
                continue
            normalized_name = (field_name or '').lower()
            if any(token in normalized_name for token in ('contract', 'agreement')):
                return field_name
        return False

    def _wgs_find_subscription_next_invoice_date_field(self, sale_order):
        fields_map = sale_order._fields
        preferred = ('recurring_next_date', 'next_invoice_date', 'recurring_next_invoice_date')
        for field_name in preferred:
            field = fields_map.get(field_name)
            if field and field.type in ('date', 'datetime'):
                return field_name

        for field_name, field in fields_map.items():
            if field.type not in ('date', 'datetime'):
                continue
            normalized_name = (field_name or '').lower()
            if all(token in normalized_name for token in ('next', 'date')) and any(
                token in normalized_name for token in ('invoice', 'recurr', 'subscription')
            ):
                return field_name
        return False

    def _wgs_assign_many2one_value(self, values, fields_map, value_id, preferred_field_names=(), comodel_checker=None):
        value_id = int(value_id or 0)
        if value_id <= 0:
            return

        for field_name in preferred_field_names:
            field = fields_map.get(field_name)
            if field and field.type == 'many2one':
                values[field_name] = value_id
                return

        if not comodel_checker:
            return
        for field_name, field in fields_map.items():
            if field_name in values or field.type != 'many2one':
                continue
            normalized_name = (field_name or '').lower()
            heuristic_name_match = (
                ('plan' in normalized_name)
                or ('recurr' in normalized_name)
                or ('period' in normalized_name)
            )
            if comodel_checker(getattr(field, 'comodel_name', '')) or heuristic_name_match:
                values[field_name] = value_id
                return

    def _wgs_assign_many2one_by_model(
        self,
        values,
        fields_map,
        value_id,
        model_name,
        preferred_field_names=(),
        required_name_tokens=(),
    ):
        value_id = int(value_id or 0)
        model_name = (model_name or '').strip()
        if value_id <= 0 or not model_name:
            return

        for field_name in preferred_field_names:
            field = fields_map.get(field_name)
            if field and field.type == 'many2one' and getattr(field, 'comodel_name', '') == model_name:
                values[field_name] = value_id
                return

        fallback_field_name = False
        tokens = tuple(token.lower() for token in (required_name_tokens or ()) if token)
        for field_name, field in fields_map.items():
            if field.type != 'many2one':
                continue
            if getattr(field, 'comodel_name', '') != model_name:
                continue
            if not fallback_field_name:
                fallback_field_name = field_name
            normalized_name = (field_name or '').lower()
            if tokens and all(token in normalized_name for token in tokens):
                values[field_name] = value_id
                return

        if fallback_field_name:
            values[fallback_field_name] = value_id

    def _wgs_assign_date_field(self, values, fields_map, date_value, preferred_field_names=()):
        if not date_value:
            return
        for field_name in preferred_field_names:
            if field_name in fields_map:
                values[field_name] = date_value
                return

    def _wgs_resolve_plan_record(self, product, plan_id=False, pricing_id=False):
        product.ensure_one()
        resolved_plan = False
        if pricing_id and 'sale.subscription.pricing' in self.env.registry:
            pricing = self.env['sale.subscription.pricing'].browse(int(pricing_id)).exists()
            if pricing:
                resolved_plan = self._wgs_extract_plan_record_from_pricing(pricing)
        if not resolved_plan and plan_id:
            resolved_plan = self._wgs_find_plan_record_by_id(int(plan_id))
        if not resolved_plan:
            resolved_plan = self._wgs_extract_plan_record_from_product(product)
        return resolved_plan

    def _wgs_find_plan_record_by_id(self, plan_id):
        if not plan_id:
            return False
        candidate_model_names = set()

        for model_name in ('sale.order', 'sale.order.line', 'product.product', 'product.template'):
            if model_name not in self.env.registry:
                continue
            for field in self.env[model_name]._fields.values():
                if field.type != 'many2one':
                    continue
                comodel_name = getattr(field, 'comodel_name', '')
                if self._wgs_is_plan_model_name(comodel_name):
                    candidate_model_names.add(comodel_name)

        for model_name in sorted(candidate_model_names):
            if model_name not in self.env.registry:
                continue
            record = self.env[model_name].browse(plan_id).exists()
            if record:
                return record
        return False

    def _wgs_get_plan_min_end_threshold(self, plan, start_date, periods_count=1):
        start_date = fields.Date.to_date(start_date) or fields.Date.context_today(self)
        interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)
        multiplier = max(1, int(periods_count or 1))
        interval_value = interval_value * multiplier
        if interval_unit == 'day':
            return start_date + timedelta(days=interval_value)
        if interval_unit == 'week':
            return start_date + relativedelta(weeks=interval_value)
        if interval_unit == 'year':
            return start_date + relativedelta(years=interval_value)
        # month by default
        return start_date + relativedelta(months=interval_value)

    def _wgs_get_plan_min_term_periods(self, plan):
        if not plan:
            return 0

        raw_value = 0
        candidate_fields = (
            'wgs_minimum_term_periods',
            'minimum_term_periods',
            'subscription_minimum_term_periods',
        )
        for field_name in candidate_fields:
            if field_name in plan._fields:
                raw_value = plan[field_name]
                break

        try:
            numeric_value = int(raw_value or 0)
        except (TypeError, ValueError):
            return 0
        return max(0, numeric_value)

    def _wgs_extract_interval_from_plan(self, plan):
        interval_value = 1
        interval_unit = 'month'
        if not plan:
            return interval_value, interval_unit

        if {'recurring_interval', 'recurring_rule_type'}.issubset(plan._fields):
            interval_value = int(plan.recurring_interval or 1)
            interval_unit = plan.recurring_rule_type or 'month'
        elif {'billing_period_value', 'billing_period_unit'}.issubset(plan._fields):
            interval_value = int(plan.billing_period_value or 1)
            interval_unit = plan.billing_period_unit or 'month'
        elif {'interval_number', 'interval_type'}.issubset(plan._fields):
            interval_value = int(plan.interval_number or 1)
            interval_unit = plan.interval_type or 'month'
        elif {'duration', 'duration_unit'}.issubset(plan._fields):
            interval_value = int(plan.duration or 1)
            interval_unit = plan.duration_unit or 'month'

        interval_value = max(1, int(interval_value or 1))
        interval_unit = (interval_unit or 'month').lower()
        if 'day' in interval_unit:
            return interval_value, 'day'
        if 'quinc' in interval_unit:
            return interval_value * 2, 'week'
        if 'week' in interval_unit:
            return interval_value, 'week'
        if 'year' in interval_unit or 'annual' in interval_unit:
            return interval_value, 'year'
        return interval_value, 'month'

    def _wgs_is_plan_model_name(self, model_name):
        model_name = (model_name or '').lower()
        if not model_name:
            return False
        if 'subscription.plan' in model_name or 'recurring.plan' in model_name:
            return True
        if 'recurr' in model_name:
            return True
        if 'subscription' in model_name and ('period' in model_name or 'template' in model_name):
            return True
        return model_name.endswith('.plan')

    def _wgs_is_pricing_model_name(self, model_name):
        model_name = (model_name or '').lower()
        if not model_name:
            return False
        if 'subscription.pricing' in model_name or 'recurring.pricing' in model_name:
            return True
        return 'subscription' in model_name and 'price' in model_name

    def _wgs_extract_plan_id_from_product(self, product):
        plan = self._wgs_extract_plan_record_from_product(product)
        return plan.id if plan else False

    def _wgs_extract_plan_record_from_product(self, product):
        product.ensure_one()

        if self._wgs_is_plan_model_name(product._name):
            return product
        if self._wgs_is_plan_model_name(product.product_tmpl_id._name):
            return product.product_tmpl_id

        # Common explicit names first.
        for source in (product, product.product_tmpl_id):
            for field_name in ('plan_id', 'subscription_plan_id', 'recurring_plan_id'):
                if field_name in source._fields and source[field_name]:
                    return source[field_name]

        # Generic fallback: relational field to a plan-like model.
        for source in (product, product.product_tmpl_id):
            for field_name, field in source._fields.items():
                if field.type not in ('many2one', 'one2many', 'many2many'):
                    continue
                comodel_name = getattr(field, 'comodel_name', '')
                normalized_name = (field_name or '').lower()
                is_candidate_name = (
                    ('plan' in normalized_name)
                    or ('recurr' in normalized_name)
                    or ('period' in normalized_name)
                )
                if not (self._wgs_is_plan_model_name(comodel_name) or is_candidate_name):
                    continue
                value = source[field_name]
                if not value:
                    continue
                if field.type == 'many2one':
                    return value
                return value[:1]
        return False

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

        candidates.extend(self._wgs_search_product_pricelist_item_records(product))

        if not candidates:
            candidates.extend(self._wgs_search_subscription_pricing_records(product))

        if not candidates:
            _logger.warning(
                'WGS POS: No recurring pricing candidates for product %s (id=%s). recurring_invoice=%s',
                product.display_name,
                product.id,
                bool(getattr(product.product_tmpl_id, 'recurring_invoice', False)),
            )

        return candidates

    def _wgs_search_product_pricelist_item_records(self, product):
        model_name = 'product.pricelist.item'
        if model_name not in self.env.registry:
            return []

        pricelist_item_model = self.env[model_name]
        fields_map = pricelist_item_model._fields
        records = pricelist_item_model.browse()

        # Search any many2one field that points to product/product.template.
        for field_name, field in fields_map.items():
            if field.type != 'many2one':
                continue
            comodel_name = getattr(field, 'comodel_name', False)
            if comodel_name == 'product.product':
                records |= pricelist_item_model.search([(field_name, '=', product.id)])
            elif comodel_name == 'product.template':
                records |= pricelist_item_model.search([(field_name, '=', product.product_tmpl_id.id)])

        output = []
        seen = set()
        for record in records:
            if record.id in seen:
                continue
            seen.add(record.id)

            plan = self._wgs_extract_plan_record_from_pricing(record)
            if not plan:
                continue

            price = self._wgs_extract_price_from_pricing(record)
            if price is None:
                continue
            interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)

            output.append({
                'sequence': self._wgs_extract_pricing_sequence(record),
                # Keep False so preferred_pricing_id matching is only used for sale.subscription.pricing ids.
                'pricing_id': False,
                'plan_id': plan.id,
                'plan_name': plan.display_name,
                'interval_label': self._wgs_extract_plan_interval_label_from_pricing(record),
                'interval_value': interval_value,
                'interval_unit': interval_unit,
                'min_term_periods': self._wgs_get_plan_min_term_periods(plan),
                'price': float(price),
            })
        return output

    def _wgs_build_pricing_candidate(self, pricing):
        plan = self._wgs_extract_plan_record_from_pricing(pricing)
        price = self._wgs_extract_price_from_pricing(pricing)
        if price is None:
            return False
        interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)
        return {
            'sequence': self._wgs_extract_pricing_sequence(pricing),
            'pricing_id': pricing.id,
            'plan_id': plan.id if plan else False,
            'plan_name': plan.display_name if plan else False,
            'interval_label': self._wgs_extract_plan_interval_label_from_pricing(pricing),
            'interval_value': interval_value,
            'interval_unit': interval_unit,
            'min_term_periods': self._wgs_get_plan_min_term_periods(plan),
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
            plan = self._wgs_extract_plan_record_from_pricing(pricing)
            price = self._wgs_extract_price_from_pricing(pricing)
            if price is None:
                continue
            interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)
            output.append({
                'sequence': self._wgs_extract_pricing_sequence(pricing),
                'pricing_id': pricing.id,
                'plan_id': plan.id if plan else False,
                'plan_name': plan.display_name if plan else False,
                'interval_label': self._wgs_extract_plan_interval_label_from_pricing(pricing),
                'interval_value': interval_value,
                'interval_unit': interval_unit,
                'min_term_periods': self._wgs_get_plan_min_term_periods(plan),
                'price': float(price),
            })
        return output

    def _wgs_extract_plan_id_from_pricing(self, pricing):
        plan = self._wgs_extract_plan_record_from_pricing(pricing)
        if plan:
            return plan.id
        return False

    def _wgs_extract_plan_name_from_pricing(self, pricing):
        plan = self._wgs_extract_plan_record_from_pricing(pricing)
        if plan:
            return plan.display_name
        return False

    def _wgs_extract_plan_interval_label_from_pricing(self, pricing):
        plan = self._wgs_extract_plan_record_from_pricing(pricing)
        if not plan:
            return ''
        interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)
        return f'{interval_value} {interval_unit}'

    def _wgs_extract_plan_record_from_pricing(self, pricing):
        if self._wgs_is_plan_model_name(pricing._name):
            return pricing

        for field_name in ('plan_id', 'subscription_plan_id', 'recurring_plan_id'):
            if field_name in pricing._fields and pricing[field_name]:
                return pricing[field_name]

        for field_name, field in pricing._fields.items():
            if field.type not in ('many2one', 'one2many', 'many2many'):
                continue
            comodel_name = getattr(field, 'comodel_name', '')
            normalized_name = (field_name or '').lower()
            is_candidate_name = (
                ('plan' in normalized_name)
                or ('recurr' in normalized_name)
                or ('period' in normalized_name)
            )
            if not (self._wgs_is_plan_model_name(comodel_name) or is_candidate_name):
                continue
            value = pricing[field_name]
            if not value:
                continue
            if field.type == 'many2one':
                return value
            return value[:1]
        return False

    def _wgs_extract_price_from_pricing(self, pricing):
        known_price_fields = (
            'fixed_price',
            'price',
            'recurring_price',
            'price_unit',
            'unit_price',
            'list_price',
            'amount',
        )
        for field_name in known_price_fields:
            if field_name not in pricing._fields:
                continue
            value = pricing[field_name]
            if value is not None:
                return float(value)

        # Generic fallback: any numeric field that looks like a price.
        for field_name, field in pricing._fields.items():
            if field_name in known_price_fields:
                continue
            if field.type not in ('float', 'monetary'):
                continue
            normalized_name = field_name.lower()
            if 'price' not in normalized_name and 'amount' not in normalized_name:
                continue
            value = pricing[field_name]
            if value is not None:
                return float(value)
        return None

    def _wgs_extract_pricing_sequence(self, pricing):
        if 'sequence' in pricing._fields and pricing.sequence is not None:
            return int(pricing.sequence)
        plan = self._wgs_extract_plan_record_from_pricing(pricing)
        if plan and 'sequence' in plan._fields:
            return int(plan.sequence or 1000)
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
