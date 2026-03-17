import json
import logging
from datetime import timedelta, date, datetime

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
    wgs_subscription_flow = fields.Selection(
        selection=[
            ('new', 'Nueva suscripción'),
            ('renewal', 'Renovación recurrente'),
        ],
        string='Flujo suscripción (POS)',
        default='new',
        copy=False,
    )
    wgs_subscription_source_id = fields.Many2one(
        'sale.order',
        string='Suscripción origen (POS)',
        copy=False,
    )

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

    def wgs_has_subscription_configuration(self):
        self.ensure_one()
        return bool(
            self.wgs_participant_ids_json
            or self.wgs_subscription_plan_id
            or self.wgs_subscription_pricing_id
            or self.wgs_subscription_start_date
            or self.wgs_subscription_end_date
            or self.wgs_subscription_source_id
        )


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
        if not self._wgs_is_subscription_buffer_ready():
            _logger.warning(
                'WGS POS: subscription buffer table is not ready yet. Skipping stage for uuid=%s',
                order_uuid,
            )
            return {'ok': False, 'reason': 'buffer_not_ready'}

        try:
            buffer_model = self.env['wgs.pos.subscription.buffer'].sudo()
            existing = buffer_model.search([('order_uuid', '=', order_uuid)], limit=1, order='id desc')
            if not configs:
                if existing:
                    existing.unlink()
                return {'ok': True, 'cleared': True}

            payload_json = json.dumps(configs)
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
    def wgs_get_subscription_charge_for_pos(
        self,
        partner_id,
        product_id,
        fallback=0.0,
        preferred_plan_id=False,
        preferred_pricing_id=False,
    ):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise UserError(_('No tienes permisos para consultar cobro de suscripción desde Punto de Venta.'))

        product = self.env['product.product'].browse(int(product_id)).exists()
        if not product:
            raise UserError(_('El producto seleccionado no existe o no está disponible.'))

        choice = self._wgs_get_recurring_pricing_choice(
            product,
            fallback=fallback,
            preferred_plan_id=preferred_plan_id,
            preferred_pricing_id=preferred_pricing_id,
        )
        recurring_price = float(choice.get('price') or 0.0)
        plan_id = choice.get('plan_id') or False
        pricing_id = choice.get('pricing_id') or False

        partner = self.env['res.partner'].browse(int(partner_id or 0)).exists()
        source_order = False
        credit_amount = 0.0
        if partner:
            source_order = self._wgs_find_active_subscription_for_partner(partner)
            if source_order:
                credit_amount = self._wgs_compute_upgrade_credit_amount(source_order)

        charge_now = max(recurring_price - credit_amount, 0.0)
        return {
            'charge_now': float(charge_now),
            'credit_amount': float(credit_amount),
            'recurring_price': float(recurring_price),
            'plan_id': plan_id,
            'pricing_id': pricing_id,
            'is_upgrade': bool(source_order),
            'source_subscription_id': source_order.id if source_order else False,
            'source_subscription_name': source_order.name if source_order else False,
        }

    @api.model
    def wgs_get_subscription_renewal_charge_for_pos(
        self,
        subscription_id,
        product_id=False,
        preferred_plan_id=False,
        preferred_pricing_id=False,
    ):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise UserError(_('No tienes permisos para consultar cobro recurrente desde Punto de Venta.'))

        try:
            subscription_id = int(subscription_id or 0)
        except (TypeError, ValueError):
            subscription_id = 0
        source_order = self.env['sale.order'].browse(subscription_id).exists()
        if not source_order:
            raise UserError(_('La suscripción origen no existe.'))
        if not self._wgs_order_has_subscription_signal(source_order):
            raise UserError(_('La orden origen no corresponde a una suscripción válida.'))
        if not self._wgs_is_subscription_order_active_for_upsell(source_order):
            raise UserError(_('La suscripción origen no está activa para renovación.'))

        recurring_lines = source_order.order_line.filtered(lambda so_line: self._wgs_is_recurring_so_line(so_line))
        if not recurring_lines:
            raise UserError(_('La suscripción origen no tiene líneas recurrentes configuradas.'))

        try:
            preferred_product_id = int(product_id or 0)
        except (TypeError, ValueError):
            preferred_product_id = 0
        recurring_line = self.env['sale.order.line']
        if preferred_product_id > 0:
            recurring_line = recurring_lines.filtered(lambda so_line: so_line.product_id.id == preferred_product_id)[:1]
        if not recurring_line:
            recurring_line = recurring_lines.sorted(key=lambda so_line: so_line.id)[:1]

        recurring_price = self._wgs_get_order_recurring_total_amount(source_order)
        if recurring_line:
            qty = abs(self._wgs_get_so_line_qty(recurring_line))
            discount = float(recurring_line.discount or 0.0) if 'discount' in recurring_line._fields else 0.0
            recurring_price = qty * float(recurring_line.price_unit or 0.0) * (1 - (discount / 100.0))
        recurring_price = round(max(float(recurring_price or 0.0), 0.0), 2)

        plan_id = False
        pricing_id = False
        if recurring_line:
            for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
                if field_name in recurring_line._fields and recurring_line[field_name]:
                    plan_id = recurring_line[field_name].id
                    break
            for field_name in ('subscription_pricing_id', 'pricing_id', 'recurring_pricing_id'):
                if field_name in recurring_line._fields and recurring_line[field_name]:
                    pricing_id = recurring_line[field_name].id
                    break

        try:
            preferred_plan_id = int(preferred_plan_id or 0)
        except (TypeError, ValueError):
            preferred_plan_id = 0
        try:
            preferred_pricing_id = int(preferred_pricing_id or 0)
        except (TypeError, ValueError):
            preferred_pricing_id = 0
        resolved_plan_id = preferred_plan_id or plan_id or False
        resolved_pricing_id = preferred_pricing_id or pricing_id or False

        return {
            'charge_now': float(recurring_price),
            'credit_amount': 0.0,
            'recurring_price': float(recurring_price),
            'plan_id': resolved_plan_id,
            'pricing_id': resolved_pricing_id,
            'is_upgrade': False,
            'is_renewal': True,
            'source_subscription_id': source_order.id,
            'source_subscription_name': source_order.name,
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
                    'interval_value': int(row.get('interval_value') or 1),
                    'interval_unit': row.get('interval_unit') or 'month',
                }
                for row in candidates
            ],
        }

    @api.model
    def wgs_get_subscription_product_catalog_for_pos(self, search_term=False, limit=80):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise UserError(_('No tienes permisos para consultar productos de suscripción desde Punto de Venta.'))

        product_model = self.env['product.product']
        domain = [('sale_ok', '=', True)]
        if 'active' in product_model._fields:
            domain.append(('active', '=', True))
        recurring_domain = ['|', ('recurring_invoice', '=', True), ('product_tmpl_id.recurring_invoice', '=', True)]
        domain = domain + recurring_domain

        if 'available_in_pos' in product_model._fields:
            domain.append(('available_in_pos', '=', True))
        elif 'available_in_pos' in self.env['product.template']._fields:
            domain.append(('product_tmpl_id.available_in_pos', '=', True))

        search_term = (search_term or '').strip()
        if search_term:
            domain += ['|', ('display_name', 'ilike', search_term), ('default_code', 'ilike', search_term)]

        try:
            limit = max(1, int(limit or 80))
        except (TypeError, ValueError):
            limit = 80
        products = product_model.search(domain, order='name asc, id asc', limit=limit)
        output = []
        for product in products:
            context = self.wgs_get_subscription_product_context_for_pos(product.id, fallback=product.lst_price)
            if not context.get('is_subscription'):
                continue
            output.append({
                'id': product.id,
                'name': product.display_name,
                'default_code': product.default_code or False,
                'max_participants_total': int(context.get('max_participants_total') or 1),
                'default_plan_id': context.get('default_plan_id') or False,
                'default_pricing_id': context.get('default_pricing_id') or False,
                'default_price': float(context.get('default_price') or 0.0),
                'plans': context.get('plans') or [],
            })
        return output

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

        flow_value = str(config_payload.get('flow') or 'new').strip().lower()
        values['wgs_subscription_flow'] = 'renewal' if flow_value == 'renewal' else 'new'

        source_subscription_id = self._wgs_to_int(config_payload.get('source_subscription_id'))
        if source_subscription_id > 0:
            values['wgs_subscription_source_id'] = source_subscription_id

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
            'flow': 'new',
            'source_subscription_id': False,
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
        data['flow'] = (
            ui_line.get('wgs_subscription_flow')
            or ui_line.get('wgsSubscriptionFlow')
            or raw_config.get('flow')
            or raw_config.get('subscription_flow')
            or 'new'
        )
        data['source_subscription_id'] = (
            ui_line.get('wgs_subscription_source_id')
            or ui_line.get('wgsSubscriptionSourceId')
            or raw_config.get('source_subscription_id')
            or raw_config.get('sourceSubscriptionId')
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
        pos_order._wgs_align_partner_from_subscription_lines()
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

            flow_value = str(config.get('flow') or 'new').strip().lower()
            write_values['wgs_subscription_flow'] = 'renewal' if flow_value == 'renewal' else 'new'

            source_subscription_id = self._wgs_to_int(config.get('source_subscription_id'))
            if source_subscription_id > 0:
                write_values['wgs_subscription_source_id'] = source_subscription_id

            if write_values:
                target_line.write(write_values)
                _logger.info(
                    'WGS POS: applied UI config to pos.order.line %s -> %s',
                    target_line.id,
                    write_values,
                )
            unmatched_lines -= target_line

    def _wgs_align_partner_from_subscription_lines(self):
        self.ensure_one()

        partner_ids = set()
        for line in self.lines.filtered(lambda item: item.qty > 0 and item.wgs_has_subscription_configuration()):
            participant_ids = line.wgs_get_participant_ids()
            if participant_ids:
                partner_ids.add(int(participant_ids[0]))

        if not partner_ids:
            return
        if len(partner_ids) > 1:
            raise UserError(
                _('La orden POS contiene configuraciones de suscripción para más de un cliente. Usa un solo titular por ticket.')
            )

        partner = self.env['res.partner'].browse(next(iter(partner_ids))).exists()
        if partner and self.partner_id != partner:
            self.partner_id = partner.id

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
            has_renewal_metadata = (
                str(config.get('flow') or '').strip().lower() == 'renewal'
                or self._wgs_to_int(config.get('source_subscription_id')) > 0
            )
            if not (
                config.get('participant_ids')
                or config.get('plan_id')
                or config.get('pricing_id')
                or config.get('start_date')
                or config.get('end_date')
                or has_renewal_metadata
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
                    lambda line: (
                        line.qty > 0
                        and line.product_id
                        and line.product_id.product_tmpl_id.recurring_invoice
                        and line.wgs_has_subscription_configuration()
                    )
                )
                if subscription_lines:
                    raise UserError(
                        _('Debes seleccionar un cliente para vender productos de suscripción desde Punto de Venta.')
                    )

            # 1) Create subscription sales for normal/positive subscription lines.
            for line in pos_order.lines.filtered(
                lambda item: (
                    item.qty > 0
                    and item.product_id
                    and item.product_id.product_tmpl_id.recurring_invoice
                    and item.wgs_has_subscription_configuration()
                )
            ):
                if line.wgs_subscription_flow == 'renewal':
                    if line.wgs_subscription_source_id and line.wgs_sale_order_id == line.wgs_subscription_source_id:
                        continue
                    pos_order._wgs_process_subscription_renewal_line(line)
                    continue
                if line.wgs_sale_order_id:
                    continue
                sale_order = pos_order._wgs_create_subscription_sale_order_from_line(line)
                line.wgs_sale_order_id = sale_order.id

            # 2) Cancel subscription sale orders when POS line is a refund.
            for line in pos_order.lines.filtered(
                lambda item: item.qty < 0 and item.product_id and item.product_id.product_tmpl_id.recurring_invoice
            ):
                pos_order._wgs_cancel_subscription_from_refund_line(line)

    def _wgs_process_subscription_renewal_line(self, line):
        self.ensure_one()

        source_order = line.wgs_subscription_source_id or line.wgs_sale_order_id
        if not source_order and self.partner_id:
            source_order = self._wgs_find_active_subscription_for_partner(self.partner_id, company=self.company_id)[:1]
        source_order = source_order.exists() if source_order else self.env['sale.order']
        if not source_order:
            raise UserError(_('No se encontró la suscripción origen para cobrar la renovación en POS.'))
        if not self._wgs_order_has_subscription_signal(source_order):
            raise UserError(_('La orden origen no corresponde a una suscripción válida para renovación.'))
        if not self._wgs_is_subscription_order_active_for_upsell(source_order):
            raise UserError(_('La suscripción origen no está activa para renovación.'))

        recurring_lines = source_order.order_line.filtered(lambda so_line: self._wgs_is_recurring_so_line(so_line))
        if not recurring_lines:
            raise UserError(_('La suscripción origen no tiene líneas recurrentes configuradas.'))

        source_line = recurring_lines.filtered(lambda so_line: so_line.product_id.id == line.product_id.id)[:1]
        if not source_line:
            source_line = recurring_lines.sorted(key=lambda so_line: so_line.id)[:1]

        today = fields.Date.context_today(self)
        _period_start, period_end = self._wgs_get_current_subscription_period_bounds(source_order, today=today)
        recurrence_delta = self._wgs_get_order_recurrence_delta(source_order)
        if period_end and today < period_end:
            renewal_anchor = period_end
        else:
            renewal_anchor = today
        next_billing_date = renewal_anchor + recurrence_delta

        values = {}
        next_field = self._wgs_find_subscription_next_invoice_date_field(source_order)
        if next_field:
            values[next_field] = next_billing_date
        if values:
            source_order.write(values)

        self._wgs_link_pos_and_sale_records(
            pos_line=line,
            sale_order=source_order,
            sale_order_line=source_line,
        )
        line.write({
            'wgs_sale_order_id': source_order.id,
            'wgs_subscription_flow': 'renewal',
            'wgs_subscription_source_id': source_order.id,
        })

        amount_paid = abs(float(line.qty or 0.0)) * float(line.price_unit or 0.0)
        if hasattr(source_order, 'message_post'):
            source_order.message_post(
                body=_(
                    'Pago recurrente recibido en POS %(pos)s por %(amount).2f. Próximo cobro: %(next_date)s.'
                ) % {
                    'pos': self.pos_reference or self.name,
                    'amount': amount_paid,
                    'next_date': fields.Date.to_string(next_billing_date),
                }
            )

        _logger.info(
            'WGS POS: renewal payment synced for subscription %s from POS %s line %s (next=%s, amount=%s)',
            source_order.name,
            self.pos_reference or self.name,
            line.id,
            next_billing_date,
            amount_paid,
        )
        return source_order

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
        sale_start_date = subscription_start_date
        if subscription_start_date < today:
            raise UserError(
                _(
                    'La fecha de inicio no puede ser anterior a %(date)s.'
                )
                % {'date': fields.Date.to_string(today)}
            )
        next_billing_date = False
        if plan_record:
            next_billing_date = self._wgs_get_plan_min_end_threshold(plan_record, sale_start_date)

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
            recurring_total = max(0.0, float(recurring_price_unit or 0.0) * float(qty or 0.0))
            paid_total = max(0.0, float(line.price_unit or 0.0) * float(qty or 0.0))
            credit_from_pos = max(0.0, recurring_total - paid_total)
            upsell_line_values = dict(line_values)
            if credit_from_pos > 0 and 'name' in sale_order_line_fields:
                base_name = upsell_line_values.get('name') or product.display_name
                upsell_line_values['name'] = _('%(name)s (Complemento por upgrade POS)') % {
                    'name': base_name,
                }

            # Immediate upgrade flow for POS:
            # create a fresh subscription order (not renewal quote), apply credit as bonus line,
            # confirm immediately, then close previous subscription.
            sale_order_fields = self.env['sale.order']._fields
            upsell_order_values = {
                'partner_id': self.partner_id.id,
                'origin': _('%(origin)s | Upsale POS de %(source)s') % {
                    'origin': self.pos_reference or self.name,
                    'source': upsell_source_order.name,
                },
                'client_order_ref': _('%(origin)s | Upsale POS de %(source)s') % {
                    'origin': self.pos_reference or self.name,
                    'source': upsell_source_order.name,
                },
                'company_id': self.company_id.id,
                'order_line': [Command.create(upsell_line_values)],
            }
            if credit_from_pos > 0:
                bonus_line_values = self._wgs_build_upgrade_bonus_line_values(credit_amount=credit_from_pos)
                if bonus_line_values:
                    upsell_order_values['order_line'].append(Command.create(bonus_line_values))

            if 'date_order' in sale_order_fields:
                upsell_order_values['date_order'] = self._wgs_convert_date_for_field_value(
                    contract_date,
                    sale_order_fields.get('date_order'),
                )
            if 'pricelist_id' in self._fields and self.pricelist_id:
                upsell_order_values['pricelist_id'] = self.pricelist_id.id

            self._wgs_assign_date_field(
                values=upsell_order_values,
                fields_map=sale_order_fields,
                date_value=contract_date,
                preferred_field_names=('first_contract_date', 'contract_date', 'date_contract'),
            )
            self._wgs_assign_date_field(
                values=upsell_order_values,
                fields_map=sale_order_fields,
                date_value=sale_start_date,
                preferred_field_names=('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date'),
            )
            if subscription_end_date:
                self._wgs_assign_date_field(
                    values=upsell_order_values,
                    fields_map=sale_order_fields,
                    date_value=subscription_end_date,
                    preferred_field_names=('end_date', 'date_end', 'subscription_end_date', 'recurring_end_date'),
                )
            if recurring_plan_id:
                for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
                    if field_name in sale_order_fields and field_name not in upsell_order_values:
                        upsell_order_values[field_name] = recurring_plan_id
                self._wgs_assign_many2one_value(
                    values=upsell_order_values,
                    fields_map=sale_order_fields,
                    value_id=recurring_plan_id,
                    preferred_field_names=('subscription_plan_id', 'plan_id', 'recurring_plan_id'),
                    comodel_checker=self._wgs_is_plan_model_name,
                )

            upsell_order = self.env['sale.order'].create(upsell_order_values)
            if 'participant_ids' in upsell_order._fields:
                upsell_order.write({'participant_ids': [Command.set(participant_ids)]})

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
                contract_date=contract_date,
                subscription_start_date=sale_start_date,
                subscription_end_date=subscription_end_date,
                next_billing_date=next_billing_date,
            )
            if self._wgs_is_order_recognized_as_subscription(upsell_order):
                self._wgs_close_source_subscription_after_upgrade(
                    source_order=upsell_source_order,
                    new_subscription_start_date=sale_start_date,
                )
            else:
                _logger.warning(
                    'WGS POS: upsell order %s is not recognized as subscription; source %s was not closed.',
                    upsell_order.name,
                    upsell_source_order.name,
                )

            _logger.info(
                'Created subscription upsell order %s from POS order %s line %s (source=%s, recurring_total=%s, paid=%s, credit=%s)',
                upsell_order.name,
                self.pos_reference,
                line.id,
                upsell_source_order.name,
                recurring_total,
                paid_total,
                credit_from_pos,
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

    def _wgs_find_active_subscription_for_partner(self, partner, company=False):
        partner.ensure_one()
        sale_order_model = self.env['sale.order']
        partner_ids = {partner.id}
        if 'commercial_partner_id' in partner._fields and partner.commercial_partner_id:
            commercial_partner = partner.commercial_partner_id
            partner_ids.add(commercial_partner.id)
            if 'child_ids' in commercial_partner._fields:
                partner_ids.update(commercial_partner.child_ids.ids)

        candidates = sale_order_model.browse()
        # Prefer shared helper used by vigencias flow.
        helper = getattr(sale_order_model, '_get_pos_subscription_orders_by_partners', None)
        if callable(helper):
            partner_batch = self.env['res.partner'].browse(list(partner_ids)).exists()
            if partner_batch:
                mapped = helper(partner_batch) or {}
                for pid in partner_batch.ids:
                    candidates |= mapped.get(pid, sale_order_model.browse())

        domain = [('state', 'in', ['sale', 'done'])]
        if 'participant_ids' in sale_order_model._fields:
            domain.extend(
                [
                    '|',
                    ('partner_id', 'in', list(partner_ids)),
                    ('participant_ids', 'in', list(partner_ids)),
                ]
            )
        else:
            domain.append(('partner_id', 'in', list(partner_ids)))

        if company and 'company_id' in sale_order_model._fields:
            domain.append(('company_id', '=', company.id))
        direct_candidates = sale_order_model.search(domain, order='id desc', limit=500)
        candidates |= direct_candidates

        # Extra fallback: any order carrying subscription_state marker for related partners.
        if 'subscription_state' in sale_order_model._fields:
            state_domain = [('state', 'in', ['sale', 'done']), ('subscription_state', '!=', False)]
            if 'participant_ids' in sale_order_model._fields:
                state_domain.extend(
                    [
                        '|',
                        ('partner_id', 'in', list(partner_ids)),
                        ('participant_ids', 'in', list(partner_ids)),
                    ]
                )
            else:
                state_domain.append(('partner_id', 'in', list(partner_ids)))
            if company and 'company_id' in sale_order_model._fields:
                state_domain.append(('company_id', '=', company.id))
            candidates |= sale_order_model.search(state_domain, order='id desc', limit=200)

        if company and 'company_id' in sale_order_model._fields:
            candidates = candidates.filtered(lambda order: order.company_id.id == company.id)

        candidates = candidates.filtered(
            lambda order: self._wgs_order_has_subscription_signal(order) and self._wgs_is_subscription_order_active_for_upsell(order)
        )
        if not candidates:
            # Last-resort fallback for DBs where recurring markers are sparse but subscription_state is set.
            relaxed_candidates = direct_candidates.filtered(
                lambda order: self._wgs_order_has_subscription_state_value(order)
                and self._wgs_is_subscription_order_active_for_upsell(order)
            )
            candidates = relaxed_candidates
        if not candidates:
            _logger.info(
                'WGS POS: no active subscription source detected for partner %s (commercial=%s, partner_ids=%s)',
                partner.id,
                partner.commercial_partner_id.id if 'commercial_partner_id' in partner._fields and partner.commercial_partner_id else False,
                sorted(partner_ids),
            )
            return candidates

        direct_owner_candidates = candidates.filtered(lambda order: order.partner_id.id in partner_ids)
        return (direct_owner_candidates or candidates).sorted(key=lambda order: order.id, reverse=True)[:1]

    def _wgs_find_partner_active_subscription_for_upsell(self):
        self.ensure_one()
        if not self.partner_id:
            return False
        candidate = self._wgs_find_active_subscription_for_partner(self.partner_id)
        if not candidate:
            return False

        all_candidates = self.env['sale.order'].search(
            [('partner_id', '=', self.partner_id.id), ('state', 'in', ['sale', 'done'])],
            order='id desc',
            limit=25,
        ).filtered(
            lambda order: self._wgs_order_has_subscription_signal(order) and self._wgs_is_subscription_order_active_for_upsell(order)
        )
        if len(all_candidates) > 1:
            _logger.warning(
                'WGS POS: multiple active subscriptions for partner %s. Using most recent %s',
                self.partner_id.id,
                candidate.name,
            )
        return candidate

    def _wgs_order_has_subscription_signal(self, sale_order):
        sale_order.ensure_one()
        check_method = getattr(sale_order, '_is_subscription_record_for_pos', None)
        if callable(check_method):
            try:
                return bool(check_method())
            except Exception as error:
                _logger.warning(
                    'WGS POS: failed to evaluate _is_subscription_record_for_pos on %s (%s). Falling back.',
                    sale_order.name,
                    error,
                )

        # 1) Standard recurring line flag
        if sale_order.order_line.filtered(lambda so_line: self._wgs_is_recurring_so_line(so_line)):
            return True

        # 2) Subscription state marker
        if 'subscription_state' in sale_order._fields:
            state_value = (sale_order.subscription_state or '').strip()
            if state_value:
                return True

        # 3) Next invoice marker
        for field_name in ('recurring_next_date', 'next_invoice_date'):
            if field_name in sale_order._fields and sale_order[field_name]:
                return True

        # 4) Plan marker
        for field_name in ('plan_id', 'subscription_plan_id', 'recurring_plan_id'):
            if field_name in sale_order._fields and sale_order[field_name]:
                return True

        return False

    def _wgs_is_subscription_order_active_for_upsell(self, sale_order):
        sale_order.ensure_one()
        if 'subscription_state' not in sale_order._fields:
            return True
        state_value = (sale_order.subscription_state or '').lower()
        if not state_value:
            return True
        return not any(token in state_value for token in self._WGS_INVALID_SUBSCRIPTION_STATE_TOKENS)

    def _wgs_is_order_recognized_as_subscription(self, sale_order):
        sale_order.ensure_one()
        check_method = getattr(sale_order, '_is_subscription_record_for_pos', None)
        if callable(check_method):
            try:
                return bool(check_method())
            except Exception as error:
                _logger.warning(
                    'WGS POS: failed to evaluate _is_subscription_record_for_pos on %s (%s). Falling back.',
                    sale_order.name,
                    error,
                )

        if not sale_order.order_line.filtered(lambda so_line: self._wgs_is_recurring_so_line(so_line)):
            return False

        if 'plan_id' in sale_order._fields and sale_order.plan_id:
            return True
        if 'subscription_state' in sale_order._fields and (sale_order.subscription_state or '').strip():
            return True
        for field_name in ('recurring_next_date', 'next_invoice_date'):
            if field_name in sale_order._fields and sale_order[field_name]:
                return True
        return False

    def _wgs_order_has_subscription_state_value(self, sale_order):
        sale_order.ensure_one()
        if 'subscription_state' not in sale_order._fields:
            return False
        state_value = (sale_order.subscription_state or '').strip()
        return bool(state_value)

    def _wgs_create_subscription_upsell_sale_order_from_line(self, source_order, line_values, credit_amount=0.0):
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

        line_commands = [Command.create(line_values)]
        self._wgs_apply_upsell_order_lines(
            upsell_order=upsell_order,
            line_values=line_values,
            credit_amount=credit_amount,
        )

        return upsell_order

    def _wgs_apply_upsell_order_lines(self, upsell_order, line_values, credit_amount=0.0):
        upsell_order.ensure_one()
        if upsell_order.order_line:
            upsell_order.order_line.unlink()

        line_commands = [Command.create(line_values)]
        bonus_line_values = self._wgs_build_upgrade_bonus_line_values(credit_amount=credit_amount)
        if bonus_line_values:
            line_commands.append(Command.create(bonus_line_values))
        upsell_order.write({'order_line': line_commands})

        recurring_plan_id = int(
            line_values.get('subscription_plan_id')
            or line_values.get('plan_id')
            or line_values.get('recurring_plan_id')
            or 0
        )
        if recurring_plan_id > 0:
            order_values = {}
            self._wgs_assign_many2one_value(
                values=order_values,
                fields_map=upsell_order._fields,
                value_id=recurring_plan_id,
                preferred_field_names=('plan_id', 'subscription_plan_id', 'recurring_plan_id'),
                comodel_checker=self._wgs_is_plan_model_name,
            )
            if order_values:
                upsell_order.write(order_values)

        return upsell_order

    def _wgs_build_upgrade_bonus_line_values(self, credit_amount=0.0):
        credit_amount = float(credit_amount or 0.0)
        if credit_amount <= 0.0:
            return False

        product = self._wgs_get_upgrade_credit_product()
        if not product:
            return False

        line_fields = self.env['sale.order.line']._fields
        values = {'product_id': product.id}
        if 'name' in line_fields:
            values['name'] = _('Bonificación upgrade de plan')

        qty_field_name = next(
            (
                field_name
                for field_name in ('product_uom_qty', 'quantity', 'qty')
                if field_name in line_fields
            ),
            False,
        )
        if qty_field_name:
            values[qty_field_name] = 1

        uom_field_name = next(
            (
                field_name
                for field_name in ('product_uom_id', 'product_uom', 'uom_id')
                if field_name in line_fields
            ),
            False,
        )
        if uom_field_name and product.uom_id:
            values[uom_field_name] = product.uom_id.id

        if 'price_unit' in line_fields:
            values['price_unit'] = -abs(credit_amount)
        if 'discount' in line_fields:
            values['discount'] = 0
        return values

    def _wgs_get_upgrade_credit_product(self):
        product_model = self.env['product.product'].sudo()
        default_code = 'WGS_UPGRADE_CREDIT'
        product = product_model.search([('default_code', '=', default_code)], limit=1)
        if product:
            return product

        values = {
            'name': 'Bonificación Upgrade WGS',
            'default_code': default_code,
            'sale_ok': True,
            'purchase_ok': False,
            'list_price': 0.0,
        }
        if 'detailed_type' in product_model._fields:
            values['detailed_type'] = 'service'
        elif 'type' in product_model._fields:
            values['type'] = 'service'
        if 'recurring_invoice' in product_model._fields:
            values['recurring_invoice'] = False
        return product_model.create(values)

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

        upsell_order = self._wgs_find_recent_subscription_upsell_order(source_order)
        if upsell_order:
            return upsell_order

        # Final fallback: create a draft SO linked to source subscription so POS flow can continue.
        return self._wgs_create_manual_subscription_upsell_order(source_order)

    def _wgs_create_manual_subscription_upsell_order(self, source_order):
        source_order.ensure_one()
        sale_order_model = self.env['sale.order']
        sale_order_fields = sale_order_model._fields

        values = {
            'partner_id': source_order.partner_id.id or self.partner_id.id,
            'company_id': source_order.company_id.id or self.company_id.id,
        }

        if 'origin' in sale_order_fields:
            values['origin'] = self.pos_reference or self.name or source_order.name
        if 'client_order_ref' in sale_order_fields:
            values['client_order_ref'] = self.pos_reference or self.name or source_order.name
        if 'pricelist_id' in sale_order_fields:
            if 'pricelist_id' in self._fields and self.pricelist_id:
                values['pricelist_id'] = self.pricelist_id.id
            elif 'pricelist_id' in source_order._fields and source_order.pricelist_id:
                values['pricelist_id'] = source_order.pricelist_id.id
        if 'user_id' in sale_order_fields and source_order.user_id:
            values['user_id'] = source_order.user_id.id
        if 'team_id' in sale_order_fields and 'team_id' in source_order._fields and source_order.team_id:
            values['team_id'] = source_order.team_id.id
        if 'payment_term_id' in sale_order_fields and 'payment_term_id' in source_order._fields and source_order.payment_term_id:
            values['payment_term_id'] = source_order.payment_term_id.id
        if 'fiscal_position_id' in sale_order_fields and 'fiscal_position_id' in source_order._fields and source_order.fiscal_position_id:
            values['fiscal_position_id'] = source_order.fiscal_position_id.id

        # Link to source subscription/order using the best matching relation field.
        self._wgs_assign_many2one_by_model(
            values=values,
            fields_map=sale_order_fields,
            value_id=source_order.id,
            model_name='sale.order',
            preferred_field_names=('subscription_id', 'origin_order_id', 'note_order'),
            required_name_tokens=('subscription',),
        )

        upsell_order = sale_order_model.create(values)
        _logger.info(
            'WGS POS: manual upsell draft created %s for source subscription %s',
            upsell_order.name,
            source_order.name,
        )
        return upsell_order

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

    def _wgs_compute_upgrade_credit_amount(self, source_order, today=False):
        source_order.ensure_one()

        recurring_total = self._wgs_get_order_recurring_total_amount(source_order)
        if recurring_total <= 0:
            return 0.0

        today = fields.Date.to_date(today) or fields.Date.context_today(self)
        period_start, period_end = self._wgs_get_current_subscription_period_bounds(source_order, today=today)
        if not period_start or not period_end:
            return 0.0
        if period_end <= period_start:
            return 0.0
        if today >= period_end:
            return 0.0

        effective_start = today if today > period_start else period_start
        total_days = max((period_end - period_start).days, 1)
        remaining_days = max((period_end - effective_start).days, 0)
        credit_amount = recurring_total * (remaining_days / total_days)
        return round(max(credit_amount, 0.0), 2)

    def _wgs_get_order_recurring_total_amount(self, sale_order):
        sale_order.ensure_one()
        recurring_lines = sale_order.order_line.filtered(
            lambda so_line: self._wgs_is_recurring_so_line(so_line) and abs(self._wgs_get_so_line_qty(so_line)) > 0
        )
        total = 0.0
        for so_line in recurring_lines:
            qty = abs(self._wgs_get_so_line_qty(so_line))
            discount = float(so_line.discount or 0.0) if 'discount' in so_line._fields else 0.0
            total += qty * float(so_line.price_unit or 0.0) * (1 - (discount / 100.0))
        return max(total, 0.0)

    def _wgs_is_recurring_so_line(self, so_line):
        so_line.ensure_one()
        if 'display_type' in so_line._fields and so_line.display_type:
            return False
        if so_line.product_id and so_line.product_id.product_tmpl_id.recurring_invoice:
            return True

        for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
            if field_name in so_line._fields and so_line[field_name]:
                return True
        for field_name in ('subscription_pricing_id', 'pricing_id', 'recurring_pricing_id'):
            if field_name in so_line._fields and so_line[field_name]:
                return True
        return False

    def _wgs_get_so_line_qty(self, so_line):
        for field_name in ('product_uom_qty', 'quantity', 'qty'):
            if field_name in so_line._fields:
                return float(so_line[field_name] or 0.0)
        return 0.0

    def _wgs_get_current_subscription_period_bounds(self, source_order, today=False):
        source_order.ensure_one()
        today = fields.Date.to_date(today) or fields.Date.context_today(self)

        period_end = self._wgs_get_first_date_from_order(source_order, ('recurring_next_date', 'next_invoice_date'))
        delta = self._wgs_get_order_recurrence_delta(source_order)
        if not period_end:
            start_date = self._wgs_get_first_date_from_order(
                source_order,
                ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date', 'date_order'),
            ) or today
            period_start = start_date
            period_end = period_start + delta
            safety_counter = 0
            while period_end <= today and safety_counter < 120:
                period_start = period_end
                period_end = period_start + delta
                safety_counter += 1
        else:
            period_start = period_end - delta

        if isinstance(period_start, datetime):
            period_start = period_start.date()
        if isinstance(period_end, datetime):
            period_end = period_end.date()

        if isinstance(period_start, date) and isinstance(period_end, date):
            return period_start, period_end
        return False, False

    def _wgs_get_order_recurrence_delta(self, sale_order):
        sale_order.ensure_one()

        interval = 1
        unit = 'month'
        if {'recurring_interval', 'recurring_rule_type'}.issubset(sale_order._fields):
            interval = int(sale_order.recurring_interval or 1)
            unit = sale_order.recurring_rule_type or 'month'
        else:
            plan = self._wgs_extract_plan_record_from_sale_order(sale_order)
            if plan:
                interval, unit = self._wgs_extract_interval_from_plan(plan)

        interval = max(1, int(interval or 1))
        unit_value = (unit or 'month').lower()
        if 'day' in unit_value:
            return relativedelta(days=interval)
        if 'week' in unit_value:
            return relativedelta(weeks=interval)
        if 'year' in unit_value:
            return relativedelta(years=interval)
        return relativedelta(months=interval)

    def _wgs_extract_plan_record_from_sale_order(self, sale_order):
        sale_order.ensure_one()
        if 'plan_id' in sale_order._fields and sale_order.plan_id:
            return sale_order.plan_id

        recurring_lines = sale_order.order_line.filtered(
            lambda so_line: self._wgs_is_recurring_so_line(so_line)
        )
        line_plan_fields = ('subscription_plan_id', 'plan_id', 'recurring_plan_id')
        for so_line in recurring_lines:
            for field_name in line_plan_fields:
                if field_name in so_line._fields and so_line[field_name]:
                    return so_line[field_name]
        return False

    def _wgs_get_first_date_from_order(self, sale_order, field_names):
        sale_order.ensure_one()
        for field_name in field_names:
            if field_name not in sale_order._fields:
                continue
            value = sale_order[field_name]
            converted = self._wgs_to_date(value)
            if converted:
                return converted
        return False

    def _wgs_to_date(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return fields.Date.to_date(value)

    def _wgs_close_source_subscription_after_upgrade(self, source_order, new_subscription_start_date):
        source_order.ensure_one()

        close_date = fields.Date.to_date(new_subscription_start_date) or fields.Date.context_today(self)
        close_date = close_date - timedelta(days=1)
        values = {}
        end_field = self._wgs_find_subscription_end_date_field(source_order)
        if end_field:
            values[end_field] = close_date
        if values:
            source_order.write(values)

        for method_name in ('action_close', 'action_subscription_close', 'set_close'):
            method = getattr(source_order, method_name, None)
            if not callable(method):
                continue
            try:
                method()
                _logger.info(
                    'WGS POS: source subscription %s closed after upgrade with %s',
                    source_order.name,
                    method_name,
                )
                return
            except Exception as error:
                _logger.warning(
                    'WGS POS: could not execute %s on source subscription %s (%s)',
                    method_name,
                    source_order.name,
                    error,
                )

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
        if original_line.wgs_subscription_flow == 'renewal':
            # Renewal refunds should not cancel the underlying subscription contract.
            line.wgs_sale_order_id = original_line.wgs_sale_order_id.id
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
            sale_orders = order.lines.filtered(
                lambda line: line.wgs_subscription_flow != 'renewal'
            ).mapped('wgs_sale_order_id').filtered(lambda so: so and so.state != 'cancel')
            for sale_order in sale_orders:
                sale_order.action_cancel()
        return result
