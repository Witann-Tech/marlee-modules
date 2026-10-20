"""Commercial quote and application boundary for WGS POS operations.

Uses only the transaction/cursor owned by Odoo. A receipt is evidence of an
application, not another subscription balance. Device delivery remains queued.
"""

import hashlib
import hmac
import json
import logging
from datetime import timedelta

from psycopg2.errors import DeadlockDetected, SerializationFailure

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

from ..subscription_contract import RULES_VERSION, canonical_json, fingerprint, validate_period


_logger = logging.getLogger(__name__)


class SubscriptionPosProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _load_pos_data_fields(self, config):
        return list(dict.fromkeys(super()._load_pos_data_fields(config) + ['recurring_invoice']))


class PosSubscriptionOperationLine(models.Model):
    _inherit = 'pos.order.line'

    wgs_operation_config_json = fields.Text(copy=False)
    wgs_application_key = fields.Char(copy=False, index=True, readonly=True)
    wgs_application_hash = fields.Char(copy=False, readonly=True)
    wgs_application_receipt = fields.Json(copy=False, readonly=True)
    wgs_application_state = fields.Selection(
        [('scheduled', 'Programada'), ('applied', 'Aplicada'), ('review', 'Pendiente heredada'), ('cancelled', 'Cancelada')],
        copy=False, index=True, readonly=True,
    )
    wgs_application_date = fields.Date(copy=False, index=True, readonly=True)
    wgs_activation_revision = fields.Char(copy=False, readonly=True)
    wgs_activation_error = fields.Text(copy=False, readonly=True)
    wgs_activation_attempts = fields.Integer(copy=False, readonly=True)
    wgs_activation_retry_at = fields.Datetime(copy=False, index=True, readonly=True)
    _wgs_application_key_unique = models.Constraint(
        'UNIQUE(wgs_application_key)', 'Esta operacion de suscripcion ya fue registrada.',
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ['wgs_operation_config_json']


class PosSubscriptionOperation(models.Model):
    _inherit = 'pos.order'

    wgs_access_sync_pending = fields.Boolean(copy=False, index=True, readonly=True)
    wgs_access_sync_partners = fields.Json(copy=False, readonly=True)
    wgs_access_sync_error = fields.Text(copy=False, readonly=True)
    wgs_access_sync_attempt_at = fields.Datetime(copy=False, readonly=True)

    def _wgs_pending_package_changes(self, source):
        return self.env['pos.order.line'].sudo().search([
            ('wgs_subscription_source_id', '=', source.id),
            ('wgs_application_state', 'in', ['scheduled', 'review']),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
        ], order='wgs_application_date, id')

    def _wgs_source_contract(self, source, include_scheduled=False):
        if not source:
            return False
        contract = source.wgs_domiciliation_contract_id
        category = source._wgs_get_subscription_state_category()
        return {
            # Preserve revision hashes of paid operations created before fixed cutoffs.
            **({'monthly_cutoff_day': source.wgs_monthly_cutoff_day} if source.wgs_monthly_cutoff_day else {}),
            'id': source.id, 'company': source.company_id.id, 'holder': source.partner_id.id,
            'state': source.state,
            'subscription_state': 'active' if category in ('progress', 'renew') else source.subscription_state,
            'plan': source.plan_id.id,
            'start': str(source.wgs_effective_start_date or source.start_date or ''),
            'end': str(source.end_date or ''), 'next': str(source.next_invoice_date or ''),
            'participants': sorted(source.participant_ids.ids),
            'lines': [(line.id, line.product_id.id, line.product_uom_qty, line.price_unit, line.discount)
                      for line in source.order_line.sorted('id') if not line.display_type],
            'contract': contract.id,
            'installments': [(item.id, item.state) for item in contract.installment_ids.sorted('id')],
            'scheduled': [(line.id, line.wgs_application_hash) for line in self._wgs_pending_package_changes(source)]
            if include_scheduled else [],
        }

    def _wgs_source_revision(self, source, include_scheduled=False):
        values = self._wgs_source_contract(source, include_scheduled=include_scheduled)
        return fingerprint(values) if values else False

    def _wgs_quote_signature(self, payload):
        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret')
        if not secret:
            raise UserError(_('No esta configurada la firma de cotizaciones de esta base de datos.'))
        return hmac.new(secret.encode(), canonical_json(payload).encode(), hashlib.sha256).hexdigest()

    def _wgs_seal_pricing_payload(self, pricing, request):
        source = request['source_order']
        if source:
            self._wgs_assert_no_due_paid_change(source)
            for scheduled in self._wgs_pending_package_changes(source):
                previous = json.loads(scheduled.wgs_pricing_snapshot_json or '{}')
                if (previous.get('domiciliation') or {}).get('selection_mode') == 'initial':
                    raise UserError(_(
                        'El contrato domiciliado ya esta pagado y programado para el %s. '
                        'Espera su activacion antes de registrar otro cobro; no contrates un segundo ciclo.'
                    ) % fields.Date.to_string(scheduled.wgs_application_date))
        product = request['product']
        if not product and source:
            product = source.order_line.filtered(
                lambda line: line.product_uom_qty > 0 and line.product_id.recurring_invoice
            )[:1].product_id
        partner = request['partner'] or (source.partner_id if source else False)
        company = source.company_id if source else self.env.company
        payload = {
            'rules_version': RULES_VERSION, 'company_id': company.id,
            'partner_id': partner.id if partner else False, 'product_id': product.id,
            'flow': request['flow'], 'source_subscription_id': source.id if source else False,
            'source_revision': self._wgs_source_revision(source, include_scheduled=True),
            'pricing': {**pricing, 'max_participants_total': product.max_participants_total or 1},
        }
        plan = self.env['sale.subscription.plan'].browse(pricing.get('plan_id') or []).exists()
        if not plan:
            raise UserError(_('La cotizacion requiere un plan recurrente existente.'))
        interval, unit = self._wgs_extract_interval_from_plan(plan)
        payload['pricing']['single_day_term'] = (interval, unit) == (1, 'day')
        if payload['pricing']['single_day_term'] and not pricing.get('domiciliation'):
            # Daily passes expire by end_date; they must not generate native invoices.
            payload['pricing']['next_billing_date'] = False
        if not pricing.get('domiciliation'):
            try:
                validate_period(pricing['subscription_start_date'], pricing['subscription_end_date'],
                                pricing.get('next_billing_date'))
            except (ValueError, TypeError, KeyError) as error:
                raise UserError(_('La cotizacion no contiene una vigencia completa y coherente.')) from error
        return {**payload['pricing'], 'commercial_quote': {'payload': payload, 'signature': self._wgs_quote_signature(payload)}}

    def _wgs_verify_commercial_quote(self, snapshot, *, product_id, partner_id, company_id, flow, source_id):
        quote = snapshot.get('commercial_quote') or {}
        payload = quote.get('payload') or {}
        signature = quote.get('signature')
        if not signature or not hmac.compare_digest(str(signature), self._wgs_quote_signature(payload)):
            raise UserError(_('La cotizacion esta incompleta o cambio. Abre de nuevo el flujo antes de cobrar.'))
        identity = {
            'rules_version': RULES_VERSION, 'product_id': product_id, 'partner_id': partner_id,
            'company_id': company_id, 'flow': flow, 'source_subscription_id': source_id or False,
        }
        if any(payload.get(key) != value for key, value in identity.items()):
            raise UserError(_('La cotizacion no corresponde al cliente, empresa, paquete u operacion del ticket.'))
        return payload

    def _wgs_validate_operation_source(self, payload):
        source = self.env['sale.order'].browse(payload.get('source_subscription_id') or []).exists()
        if payload.get('source_subscription_id') and (
            not source or self._wgs_source_revision(source, include_scheduled=True) != payload.get('source_revision')
        ):
            raise UserError(_('La suscripcion cambio desde la cotizacion. Actualiza la operacion; no repitas un cobro ya recibido.'))
        if source:
            self._wgs_assert_no_due_paid_change(source)
        return source

    def _wgs_assert_no_due_paid_change(self, source):
        if self.env['pos.order.line'].sudo().search([
            ('wgs_subscription_source_id', '=', source.id),
            ('wgs_application_state', 'in', ['scheduled', 'review']),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
            ('wgs_application_date', '<=', self._wgs_get_subscription_business_today_for_pos()),
        ], limit=1):
            raise UserError(_(
                'Ya existe un periodo pagado pendiente de activacion automatica. '
                'No se registrara otro cobro sobre ese periodo.'
            ))

    def _wgs_settle_due_source_changes(self, source):
        """Finish already-paid periods before calculating another purchase."""
        today = self._wgs_get_subscription_business_today_for_pos(company=source.company_id)
        due = self._wgs_pending_package_changes(source).filtered(
            lambda line: line.wgs_application_date and line.wgs_application_date <= today
        )
        if len(due) > 100:
            raise UserError(_('La cola de periodos pagados excede el lote automatico; no vuelvas a cobrar.'))
        for line in due:
            if not line.order_id._wgs_activate_package_change(line):
                raise UserError(_(
                    'El pago %(ticket)s ya cubre un periodo pendiente. '
                    'Su activacion se reintenta automaticamente; no vuelvas a cobrar.'
                ) % {'ticket': line.order_id.pos_reference or line.order_id.name})

    def _wgs_validate_full_membership_refund(self, original, qty, price_unit, discount, refund_line=False):
        if not original or original.order_id.state not in ('paid', 'done', 'invoiced'):
            raise UserError(_('El reembolso requiere la linea de membresia original pagada.'))
        currency = original.order_id.currency_id
        if (abs(abs(qty) - original.qty) > 0.00001
                or currency.compare_amounts(price_unit, original.price_unit)
                or abs(discount - original.discount) > 0.00001):
            raise UserError(_('Las membresias solo permiten reembolso total, sin cambiar cantidad, precio ni descuento.'))
        previous = self.env['pos.order.line'].search([
            ('id', '!=', refund_line.id if refund_line else 0),
            ('order_id.state', 'in', ('paid', 'done', 'invoiced')), ('qty', '<', 0),
            '|', ('refunded_orderline_id', '=', original.id),
            ('wgs_subscription_refund_origin_line_id', '=', original.id),
        ], limit=1)
        if previous:
            raise UserError(_('Esta compra de membresia ya tiene un reembolso registrado.'))

    @api.model
    def wgs_validate_subscription_refunds_for_pos(self, refunds):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para validar reembolsos POS.'))
        seen = set()
        for values in refunds:
            original = self.env['pos.order.line'].browse(int(values['original_line_id'])).exists()
            if not original or not original.product_id.recurring_invoice:
                continue
            if original.id in seen:
                raise UserError(_('El mismo pago de membresia no puede reembolsarse dos veces.'))
            seen.add(original.id)
            self._wgs_validate_full_membership_refund(
                original, float(values['qty']), float(values['price_unit']), float(values['discount']),
            )
        return True

    def _wgs_normalize_commercial_config(self, config, *, partner_id, company_id, check_source=True):
        """Resolve browser metadata to the exact backend quote before payment."""
        config = dict(config)
        if config.get('flow') in ('pending_charge', 'cancellation_refund'):
            return config
        snapshot = config.get('pricing_snapshot') or {}
        payload = self._wgs_verify_commercial_quote(
            snapshot, product_id=self._wgs_to_int(config.get('product_id')),
            partner_id=partner_id, company_id=company_id, flow=config.get('flow') or 'new',
            source_id=self._wgs_to_int(config.get('source_subscription_id')),
        )
        if check_source:
            source = self._wgs_validate_operation_source(payload)
            eligibility = self.with_company(company_id).wgs_validate_subscription_product_eligibility_for_pos(
                partner_id, payload['product_id'], payload['flow'], source.id or False,
            )
            if not eligibility or not eligibility.get('ok'):
                raise UserError((eligibility or {}).get('error_message') or _('El cliente no puede contratar este paquete.'))
        pricing = payload['pricing']
        if not self.env['sale.subscription.plan'].browse(pricing.get('plan_id') or []).exists():
            raise UserError(_('El plan cotizado ya no existe. Actualiza el paquete antes de cobrar.'))
        locked_price = (config.get('pricing_lock') or {}).get('price_unit')
        if locked_price is not None and abs(float(locked_price) - float(pricing['ticket_charge_now'])) > 0.01:
            raise UserError(_('El importe del ticket difiere de la cotizacion. Actualiza antes de cobrar.'))
        for key in ('plan_id', 'pricing_id'):
            if config.get(key) and self._wgs_to_int(config[key]) != self._wgs_to_int(pricing.get(key)):
                raise UserError(_('El plan del ticket no corresponde a la cotizacion.'))
            config[key] = pricing.get(key) or False
        product = self.env['product.product'].browse(payload['product_id']).exists()
        qty = self._wgs_to_float(config.get('quantity')) or 1.0
        participants = sorted(set(int(value) for value in config.get('participant_ids', []) if int(value) > 0) | {partner_id})
        if len(participants) > int((product.max_participants_total or 1) * qty):
            raise UserError(_('Los participantes exceden el cupo del paquete contratado.'))
        if len(self.env['res.partner'].browse(participants).exists()) != len(participants):
            raise UserError(_('Uno de los participantes ya no existe.'))
        config.update({
            'participant_ids': participants,
            'start_date': pricing.get('subscription_start_date'),
            'end_date': pricing.get('subscription_end_date'),
            'pricing_snapshot': {**pricing, 'commercial_quote': snapshot['commercial_quote']},
        })
        return config

    def _wgs_validate_ticket_memberships(self, lines, configs):
        """Preflight uses server product flags, not cached browser catalog flags."""
        by_uuid = {config['line_uuid']: config for config in configs}
        products = self.env['product.product'].browse([
            self._wgs_to_int(line.get('product_id')) for line in lines
        ]).exists()
        recurring_ids = set(products.filtered('recurring_invoice').ids)
        seen_sources = set()
        for line in lines:
            if self._wgs_to_int(line.get('product_id')) not in recurring_ids or float(line.get('qty') or 0) <= 0:
                continue
            config = by_uuid.get(line.get('uuid'))
            if not config:
                raise UserError(_('Hay una membresia sin configurar. Usa Nueva suscripcion, Renovar o Reinscribir antes de cobrar.'))
            if self._wgs_to_int(config['product_id']) != self._wgs_to_int(line['product_id']):
                raise UserError(_('El paquete cotizado no corresponde a la linea del ticket.'))
            if abs(float(config.get('quantity') or 1) - float(line['qty'])) > 0.00001:
                raise UserError(_('Cambio la cantidad del paquete. Actualiza la cotizacion antes de cobrar.'))
            pricing = config.get('pricing_snapshot') or {}
            if abs(float(line.get('price_unit') or 0) - float(pricing.get('ticket_charge_now') or 0)) > 0.01:
                raise UserError(_('El precio del ticket difiere de la cotizacion de membresia.'))
            if abs(float(line.get('discount') or 0) - float(config.get('discount_percent') or 0)) > 0.00001:
                raise UserError(_('El descuento del ticket difiere del descuento autorizado.'))
            source_id = config.get('source_subscription_id')
            if source_id and source_id in seen_sources:
                raise UserError(_('Agrega una sola operacion por suscripcion en cada ticket.'))
            if source_id:
                seen_sources.add(source_id)

    def _wgs_check_applied_config_replay(self, line, config):
        """A lost HTTP response is not a new commercial operation."""
        incoming = {
            **self._wgs_line_operation_input(line),
            'product': self._wgs_to_int(config.get('product_id')),
            'qty': float(config.get('quantity') or 1),
            'price': float(config['pricing_snapshot']['ticket_charge_now']),
            'discount': float(config.get('discount_percent') or 0),
            'flow': config.get('flow') or 'new',
            'source': self._wgs_to_int(config.get('source_subscription_id')) or False,
            'participants': sorted(config.get('participant_ids') or []),
            'snapshot': config['pricing_snapshot'],
            'pending': self._wgs_to_int(config.get('pending_move_id')) or False,
        }
        if fingerprint(incoming) != line.wgs_application_hash:
            raise UserError(_('El ticket ya fue aplicado con otros datos. No repitas el cobro; revisa la venta registrada.'))

    def _wgs_line_operation_input(self, line):
        return {
            'product': line.product_id.id, 'partner': line.order_id.partner_id.id,
            'company': line.order_id.company_id.id, 'qty': line.qty,
            'price': line.price_unit, 'discount': line.discount,
            'flow': line.wgs_subscription_flow,
            'source': line.wgs_subscription_source_id.id,
            'participants': sorted(line.wgs_get_participant_ids()),
            'snapshot': json.loads(line.wgs_pricing_snapshot_json or '{}'),
            'pending': line.wgs_subscription_pending_move_id.id,
            'refund': (line.refunded_orderline_id or line.wgs_subscription_refund_origin_line_id).id,
        }

    def _wgs_lock_operation_records(self, lines):
        # Stable lock order; all locks are released with Odoo's transaction.
        originals = lines.mapped('refunded_orderline_id') | lines.mapped('wgs_subscription_refund_origin_line_id')
        orders = self | originals.mapped('order_id')
        orders.flush_recordset()
        self.env.cr.execute('SELECT id FROM pos_order WHERE id = ANY(%s) ORDER BY id FOR UPDATE', [orders.ids])
        orders.invalidate_recordset()
        operation_lines = lines | originals
        operation_lines.flush_recordset()
        operation_lines.invalidate_recordset()
        sources = operation_lines.mapped('wgs_subscription_source_id') | operation_lines.mapped('wgs_sale_order_id')
        partners = orders.mapped('partner_id') | sources.mapped('partner_id')
        if partners:
            partners.flush_recordset()
            self.env.cr.execute('SELECT id FROM res_partner WHERE id = ANY(%s) ORDER BY id FOR UPDATE', [partners.ids])
        if sources:
            sources.flush_recordset()
            self.env.cr.execute('SELECT id FROM sale_order WHERE id = ANY(%s) ORDER BY id FOR UPDATE', [sources.ids])
            sources.invalidate_recordset()
        lines.invalidate_recordset()
        return sources

    def _wgs_finalize_paid_access(self, sources, affected):
        """Failure of an access projection must not ask the cashier to charge twice."""
        self.ensure_one()
        affected = sorted(set(affected) | sources._wgs_get_access_related_partner_ids())
        self.write({
            'wgs_access_sync_pending': True, 'wgs_access_sync_partners': affected,
            'wgs_access_sync_attempt_at': fields.Datetime.now(),
        })
        try:
            with self.env.cr.savepoint():
                sources._wgs_update_access_snapshot(force=True)
                sources.with_context(wgs_defer_access_sync=False, access_sync_priority=True)._wgs_sync_access_control_people(
                    extra_partner_ids=affected,
                )
        except (DeadlockDetected, SerializationFailure):
            # Let Odoo retry the complete transaction with a fresh snapshot.
            raise
        except Exception as error:
            _logger.exception('WGS paid order %s has pending access projection', self.id)
            self.write({'wgs_access_sync_error': str(error)[:2000]})
        else:
            self.write({'wgs_access_sync_pending': False, 'wgs_access_sync_error': False, 'wgs_access_sync_partners': False})

    @api.model
    def _wgs_retry_paid_access(self, limit=100):
        pending = self.sudo().search([
            ('wgs_access_sync_pending', '=', True),
            '|', ('wgs_access_sync_attempt_at', '=', False),
            ('wgs_access_sync_attempt_at', '<=', fields.Datetime.now() - timedelta(hours=1)),
        ], order='wgs_access_sync_attempt_at, id', limit=limit)
        for order in pending:
            order._wgs_lock_operation_records(order.lines)
            if not order.wgs_access_sync_pending:
                continue
            order._wgs_finalize_paid_access(order.lines.mapped('wgs_sale_order_id'), order.wgs_access_sync_partners or [])

    def _wgs_sync_subscription_sales(self):
        for order in self.sorted('id'):
            if order.state not in ('paid', 'done', 'invoiced'):
                continue
            lines = order.lines.filtered(lambda line: line.qty and line.product_id.recurring_invoice)
            if not lines:
                continue
            sources = order._wgs_lock_operation_records(lines)
            affected = sources._wgs_get_access_related_partner_ids()
            affected.update(order.partner_id.ids)
            changed = False
            for line in lines.sorted('id'):
                input_hash = fingerprint(order._wgs_line_operation_input(line))
                if line.wgs_application_state:
                    if line.wgs_application_hash != input_hash:
                        raise UserError(_('Una operacion ya registrada cambio de contenido. Requiere revision, no otro cobro.'))
                    continue
                # Legacy links remain evidence of application even after expiry.
                if line.wgs_sale_order_id:
                    continue
                if line.qty > 0 and line.wgs_subscription_flow == 'new':
                    # FOR UPDATE alone cannot refresh a Repeatable Read snapshot.
                    # Version the locked holder row, without changing business or
                    # audit fields, so competing first sales retry on fresh history.
                    self.env.cr.execute(
                        'UPDATE res_partner SET write_date = write_date WHERE id = %s',
                        [order.partner_id.id],
                    )
                scoped_order = order.with_context(wgs_defer_access_sync=True)
                scoped_line = line.with_env(scoped_order.env)
                before = order._wgs_source_revision(line.wgs_subscription_source_id)
                if line.qty > 0 and line.wgs_subscription_flow != 'pending_charge':
                    snapshot = json.loads(line.wgs_pricing_snapshot_json or '{}')
                    payload = order._wgs_verify_commercial_quote(
                        snapshot, product_id=line.product_id.id, partner_id=order.partner_id.id,
                        company_id=order.company_id.id, flow=line.wgs_subscription_flow,
                        source_id=line.wgs_subscription_source_id.id,
                    )
                    order._wgs_validate_operation_source(payload)
                    eligibility = order.with_company(order.company_id).wgs_validate_subscription_product_eligibility_for_pos(
                        order.partner_id.id, line.product_id.id, line.wgs_subscription_flow,
                        line.wgs_subscription_source_id.id,
                    )
                    if not eligibility or not eligibility.get('ok'):
                        raise UserError((eligibility or {}).get('error_message') or _('La operacion no cumple las reglas de la membresia.'))
                result = scoped_order._wgs_apply_subscription_operation(scoped_line)
                line.write({
                    'wgs_sale_order_id': result.id,
                    'wgs_application_key': '%s:%s' % (order.uuid, line.uuid),
                    'wgs_application_hash': fingerprint(order._wgs_line_operation_input(line)),
                    'wgs_application_state': line.wgs_application_state or 'applied',
                    'wgs_activation_revision': order._wgs_source_revision(result),
                    'wgs_application_receipt': {
                        'rules_version': RULES_VERSION, 'before': before,
                        'after': order._wgs_source_revision(result), 'subscription_id': result.id,
                        'period_start': str(line.wgs_subscription_start_date or ''),
                        'period_end': str(line.wgs_subscription_end_date or ''),
                    },
                })
                sources |= result.with_env(order.env)
                changed = True
            if changed:
                order._wgs_finalize_paid_access(sources, affected)

    def _wgs_apply_subscription_operation(self, line, *, activation=False):
        """One transactional boundary for checkout and deferred activation.

        A receipt may be recorded only after the native result agrees with the
        purchased quote. Historical/applied lines never enter this boundary.
        """
        self.ensure_one()
        line.ensure_one()
        if activation and (
            line.qty <= 0 or line.wgs_subscription_flow != 'renewal'
            or line.wgs_application_state not in ('scheduled', 'review')
            or fingerprint(self._wgs_line_operation_input(line)) != line.wgs_application_hash
        ):
            raise UserError(_('El cambio programado ya no conserva el contenido del pago original.'))
        pricing_state = False
        before = False
        expected_participants = False
        if line.qty > 0 and line.wgs_subscription_flow != 'pending_charge':
            pricing_state = self._wgs_get_persisted_subscription_pricing_from_pos_line(line)
            if not pricing_state['snapshot'].get('commercial_quote'):
                raise UserError(_('La operacion requiere su cotizacion firmada antes de aplicarse.'))
            ticket_price = pricing_state['snapshot'].get('ticket_charge_now')
            if ticket_price is None or self.currency_id.compare_amounts(line.price_unit, ticket_price):
                raise UserError(_('El precio de la membresia pagada no coincide con su cotizacion firmada.'))
            before = self._wgs_source_revision(line.wgs_subscription_source_id)
            source = line.wgs_subscription_source_id
            same_package = source and source.order_line.filtered(
                lambda item: item.product_id.recurring_invoice and item.product_uom_qty > 0
            ).product_id == line.product_id
            if line.wgs_subscription_flow == 'renewal' and same_package and not activation:
                expected_participants = set(source.participant_ids.ids)
        result = self._wgs_dispatch_subscription_operation(line, activation=activation)
        if not result:
            raise UserError(_('No se obtuvo el resultado comercial de la operacion de suscripcion.'))
        if pricing_state:
            self._wgs_assert_subscription_application(
                line, result, pricing_state, before=before, activation=activation,
                expected_participants=expected_participants,
            )
        elif line.qty < 0:
            self._wgs_assert_subscription_refund(result)
        return result

    def _wgs_dispatch_subscription_operation(self, line, *, activation=False):
        if line.qty < 0:
            original = line.refunded_orderline_id or line.wgs_subscription_refund_origin_line_id
            if original and (original.product_id != line.product_id or original.order_id.company_id != self.company_id):
                raise UserError(_('El reembolso debe corresponder al producto y empresa del pago original.'))
            self._wgs_validate_full_membership_refund(original, line.qty, line.price_unit, line.discount, line)
            self._wgs_cancel_subscription_from_refund_line(line)
            scheduled = self.env['pos.order.line'].search([
                ('wgs_subscription_source_id', '=', line.wgs_sale_order_id.id),
                ('wgs_application_state', 'in', ['scheduled', 'review']),
            ])
            scheduled.write({'wgs_application_state': 'cancelled'})
            contract = line.wgs_sale_order_id.wgs_domiciliation_contract_id
            if contract:
                contract.write({'state': 'cancelled'})
            return line.wgs_sale_order_id
        handlers = {
            'renewal': self._wgs_process_subscription_renewal_line,
            'reenroll': self._wgs_process_subscription_reenroll_line,
            'pending_charge': self._wgs_process_subscription_pending_charge_line,
            'new': self._wgs_create_subscription_sale_order_from_line,
            'upsale': self._wgs_create_subscription_sale_order_from_line,
        }
        if line.wgs_subscription_flow not in handlers:
            raise UserError(_('El flujo de suscripcion no es valido.'))
        if activation and line.wgs_subscription_flow != 'renewal':
            raise UserError(_('Solo una renovacion pagada puede activar un cambio programado.'))
        return handlers[line.wgs_subscription_flow](line)

    @api.model
    def _wgs_apply_due_package_changes(self, limit=100):
        today = self._wgs_get_subscription_business_today_for_pos()
        remaining = max(1, int(limit))
        applied = 0
        attempted = []
        while remaining:
            lines = self._wgs_select_due_package_changes(today, remaining, exclude_ids=attempted)
            if not lines:
                break
            for line in lines:
                applied += bool(self._wgs_activate_package_change(line))
                attempted.append(line.id)
            remaining -= len(lines)
        return applied

    def _wgs_select_due_package_changes(self, today, limit, exclude_ids=()):
        Line = self.env['pos.order.line'].sudo()
        self.env['pos.order'].flush_model(['state'])
        Line.flush_model(['order_id', 'wgs_application_state', 'wgs_application_date',
                          'wgs_subscription_source_id', 'wgs_activation_retry_at'])
        # Select the head of each subscription queue before limiting the batch.
        # Legacy quarantines rejoin the same queue; failures never become terminal.
        self.env.cr.execute('''
            SELECT candidate.id FROM pos_order_line candidate
              JOIN pos_order paid_order ON paid_order.id = candidate.order_id
             WHERE candidate.wgs_application_state IN ('scheduled', 'review')
               AND paid_order.state IN ('paid', 'done', 'invoiced')
               AND candidate.wgs_application_date <= %s
               AND (candidate.wgs_activation_retry_at IS NULL OR candidate.wgs_activation_retry_at <= %s)
               AND candidate.id != ALL(%s)
               AND NOT EXISTS (
                   SELECT 1 FROM pos_order_line earlier
                     JOIN pos_order earlier_order ON earlier_order.id = earlier.order_id
                    WHERE earlier.wgs_subscription_source_id = candidate.wgs_subscription_source_id
                      AND earlier_order.state IN ('paid', 'done', 'invoiced')
                      AND earlier.wgs_application_state IN ('scheduled', 'review')
                      AND (earlier.wgs_application_date, earlier.id)
                              < (candidate.wgs_application_date, candidate.id)
               )
             ORDER BY candidate.wgs_activation_retry_at ASC NULLS FIRST,
                      candidate.wgs_application_date, candidate.id LIMIT %s
        ''', [today, fields.Datetime.now(), list(exclude_ids), max(1, int(limit))])
        return Line.browse([row[0] for row in self.env.cr.fetchall()])

    def _wgs_is_automatic_inclusive_close(self, source, line):
        """Require audit evidence; a manual cancellation must never reopen."""
        root = self.env.ref('base.user_root')
        reasons = self.env['sale.order.close.reason']
        for xmlid in (
            'sale_subscription.close_reason_end_of_contract',
            'sale_subscription.close_reason_auto_close_limit_reached',
            'sale_subscription.close_reason_unpaid_subscription',
        ):
            reasons |= self.env.ref(xmlid, raise_if_not_found=False) or reasons.browse()
        if (source.state != 'sale' or source._wgs_get_subscription_state_category() not in ('closed', 'cancel')
                or source.write_uid != root or source.close_reason_id not in reasons
                or not source.write_date or not line.create_date or line.create_date > source.write_date
                or source.next_invoice_date != line.wgs_application_date
                or self._wgs_get_subscription_business_date_from_datetime_for_pos(source.write_date) != source.end_date):
            return False
        return bool(self.env['mail.tracking.value'].sudo().search([
            ('field_id.model', '=', 'sale.order'), ('field_id.name', '=', 'subscription_state'),
            ('mail_message_id.model', '=', 'sale.order'), ('mail_message_id.res_id', '=', source.id),
            ('mail_message_id.author_id', '=', root.partner_id.id),
            ('mail_message_id.date', '>=', source.write_date - timedelta(minutes=1)),
            ('mail_message_id.date', '<=', source.write_date + timedelta(minutes=1)),
        ], limit=1))

    def _wgs_prepare_paid_activation_source(self, source, line):
        values = self._wgs_source_contract(source)
        if fingerprint(values) == line.wgs_activation_revision:
            return False
        active_values = {**values, 'subscription_state': 'active'}
        if (fingerprint(active_values) != line.wgs_activation_revision
                or not self._wgs_is_automatic_inclusive_close(source, line)):
            raise UserError(_('La membresia pagada tiene cambios comerciales ajenos a su activacion automatica.'))
        scoped = self.with_context(wgs_defer_access_sync=True)
        scoped._wgs_reactivate_subscription_order_for_pos(source.with_env(scoped.env))
        source.with_context(wgs_defer_access_sync=True).write({'close_reason_id': False})
        if self._wgs_source_revision(source) != line.wgs_activation_revision:
            raise UserError(_('No se recupero exactamente el contrato previo al cierre automatico.'))
        return True

    def _wgs_activate_package_change(self, line):
        try:
            with self.env.cr.savepoint():
                order = line.order_id
                sources = order._wgs_lock_operation_records(line)
                if line.wgs_application_state not in ('scheduled', 'review'):
                    return False
                if order.state not in ('paid', 'done', 'invoiced'):
                    return False
                source = line.wgs_subscription_source_id
                if not source:
                    raise UserError(_('El cambio pagado perdio su suscripcion origen; requiere revision.'))
                first_pending = self.env['pos.order.line'].sudo().search([
                    ('wgs_subscription_source_id', '=', source.id),
                    ('wgs_application_state', 'in', ['scheduled', 'review']),
                    ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
                ], order='wgs_application_date, id', limit=1)
                if first_pending != line:
                    return False
                receipt = line.wgs_application_receipt or {}
                recovered = order._wgs_prepare_paid_activation_source(source, line)
                affected = sources._wgs_get_access_related_partner_ids()
                scoped = order.with_context(wgs_defer_access_sync=True)
                scoped._wgs_apply_subscription_operation(line.with_env(scoped.env), activation=True)
                after = order._wgs_source_revision(source)
                line.write({'wgs_application_state': 'applied', 'wgs_application_receipt': {
                    **receipt, 'activation_after': after,
                    'activated_at': fields.Datetime.to_string(fields.Datetime.now()),
                    **({'automatic_close_recovered': True} if recovered else {}),
                }, 'wgs_activation_error': False, 'wgs_activation_retry_at': False})
                order._wgs_pending_package_changes(source).write({'wgs_activation_revision': after})
                order._wgs_finalize_paid_access(sources, affected)
                return True
        except (DeadlockDetected, SerializationFailure):
            raise
        except Exception as error:
            # A rolled-back savepoint releases its locks. Recheck before
            # retrying so a concurrent refund/activation is not undone.
            line.order_id._wgs_lock_operation_records(line)
            if line.wgs_application_state not in ('scheduled', 'review'):
                return False
            line.write({
                'wgs_application_state': 'scheduled',
                'wgs_activation_error': str(error)[:2000],
                'wgs_activation_attempts': line.wgs_activation_attempts + 1,
                'wgs_activation_retry_at': fields.Datetime.now() + timedelta(minutes=15),
            })
            _logger.exception('WGS paid activation will retry automatically: line=%s', line.id)
            return False


class SaleOrderOperationCron(models.Model):
    _inherit = 'sale.order'

    wgs_subscription_operation_line_ids = fields.One2many(
        'pos.order.line', 'wgs_subscription_source_id', readonly=True, copy=False,
    )

    @api.model
    def get_partner_subscription_detail_for_pos(self, partner_id, company_id=False):
        # Catch up only this authorized customer's due purchases, before choosing
        # Renew/Reenroll. Never run a global activation from a directory read.
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar suscripciones desde Punto de Venta.'))
        company = self._wgs_resolve_pos_company_for_pos(company_id)
        partner = self._wgs_browse_partner_for_pos(partner_id)
        if partner:
            sources = self._get_pos_subscription_orders(partner, company=company)
            due = self.env['pos.order.line'].sudo().search([
                ('wgs_subscription_source_id', 'in', sources.ids),
                ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
                ('wgs_application_state', 'in', ['scheduled', 'review']),
                ('wgs_application_date', '<=', self._wgs_subscription_business_today_for_pos(company=company)),
                '|', ('wgs_activation_retry_at', '=', False),
                ('wgs_activation_retry_at', '<=', fields.Datetime.now()),
            ], order='wgs_application_date, id', limit=100)
            for line in due:
                line.order_id._wgs_activate_package_change(line)
        return super().get_partner_subscription_detail_for_pos(partner_id, company_id=company_id)

    @api.model
    def _wgs_get_subscription_auto_close_candidate_domain(self, today):
        # A bounded activation batch may leave already-paid changes for the next
        # run. Do not close their source before those changes can be applied.
        return super()._wgs_get_subscription_auto_close_candidate_domain(today) & Domain(
            'wgs_subscription_operation_line_ids', 'not any', Domain([
                ('wgs_application_state', 'in', ['scheduled', 'review']),
                ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
                ('wgs_application_date', '<=', today),
            ]),
        )

    def _build_pos_subscription_status_item(self, today):
        item = super()._build_pos_subscription_status_item(today)
        if item:
            item['access_application_pending'] = bool(self.env['pos.order'].sudo().search([
                ('wgs_access_sync_pending', '=', True), ('lines.wgs_sale_order_id', '=', self.id),
            ], limit=1))
            changes = self.env['pos.order.line'].sudo().search([
                ('wgs_subscription_source_id', '=', self.id),
                ('wgs_application_state', 'in', ['scheduled', 'review']),
                ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
            ], order='wgs_application_date, id')
            item['scheduled_changes'] = [{
                'product': line.product_id.display_name,
                'start': fields.Date.to_string(line.wgs_application_date),
                'end': fields.Date.to_string(line.wgs_subscription_end_date),
                'state': line.wgs_application_state,
                'retry_pending': bool(line.wgs_activation_error or line.wgs_application_state == 'review'),
            } for line in changes]
            if changes:
                last = changes[-1]
                item['renewal_defaults'] = {
                    'product_id': last.product_id.id,
                    'product_name': last.product_id.display_name,
                    'plan_id': last.wgs_subscription_plan_id,
                    'pricing_id': last.wgs_subscription_pricing_id,
                    'participant_ids': last.wgs_get_participant_ids(),
                    'max_participants_total': last.product_id.max_participants_total or 1,
                }
        return item

    def _cron_wgs_sync_subscription_access_control(self, batch_limit=None):
        self.env['pos.order']._wgs_apply_due_package_changes()
        self.env['pos.order']._wgs_retry_paid_access()
        return super()._cron_wgs_sync_subscription_access_control(batch_limit=batch_limit)

    def _cron_wgs_close_overdue_subscriptions(self, limit=None):
        self.env['pos.order']._wgs_apply_due_package_changes()
        return super()._cron_wgs_close_overdue_subscriptions(limit=limit)
