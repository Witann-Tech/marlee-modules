"""Explicit cancellation, applied atomically with its fee or a zero-fee confirmation."""

import hmac
import json
import math
from uuid import uuid4

from odoo import _, api, Command, fields, models
from odoo.exceptions import AccessError, UserError

from ..subscription_contract import fingerprint


CANCELLATION_FLOW = 'cancellation_charge'


class ResCompany(models.Model):
    _inherit = 'res.company'

    wgs_cancellation_product_id = fields.Many2one(
        'product.product', copy=False, readonly=True, check_company=True, prefetch=False,
    )


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    wgs_cancellation_fee = fields.Boolean(copy=False, readonly=True, prefetch=False)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    wgs_pos_cancellation_receipt = fields.Json(copy=False, readonly=True, prefetch=False)

    def _wgs_can_cancel_for_pos(self):
        self.ensure_one()
        return self.state in ('sale', 'done') and (
            self.wgs_domiciliation_contract_id.state == 'active'
            or bool(self.env['pos.order']._wgs_pending_package_changes(self))
            or self._wgs_subscription_operation_policy_for_pos()['state_key'] not in ('closed', 'cancel', 'draft', 'upsell')
        )

    def _build_pos_subscription_status_item(self, today):
        item = super()._build_pos_subscription_status_item(today)
        if item:
            item['can_cancel'] = bool(self._wgs_can_cancel_for_pos())
        return item


class PosSubscriptionCancellation(models.Model):
    _inherit = 'pos.order'

    def _wgs_cancellation_source(self, subscription_id, company_id=False):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para cancelar paquetes desde el POS.'))
        source = self._wgs_browse_source_subscription_for_pos(subscription_id)
        company = self.env['sale.order']._wgs_resolve_pos_company_for_pos(company_id)
        if (company not in self.env.companies or not source or source.company_id != company
                or not source._is_subscription_record_for_pos()):
            raise AccessError(_('Cancela el paquete exclusivamente desde el POS de su empresa de origen.'))
        return source.with_company(company)

    def _wgs_cancellation_product(self, company):
        company = company.sudo()
        product = company.wgs_cancellation_product_id
        if not product:
            self.env.cr.execute('SELECT id FROM res_company WHERE id = %s FOR UPDATE', [company.id])
            company.invalidate_recordset(['wgs_cancellation_product_id'])
            product = company.wgs_cancellation_product_id
            if not product:
                product = self.env['product.product'].sudo().with_company(company).create({
                    'name': _('Cargo por cancelacion de paquete'), 'type': 'service',
                    'company_id': company.id, 'available_in_pos': True,
                    'sale_ok': True, 'purchase_ok': False, 'recurring_invoice': False,
                    'wgs_cancellation_fee': True, 'list_price': 0,
                    'taxes_id': [Command.set(company.account_sale_tax_id.ids)],
                })
                company.wgs_cancellation_product_id = product
        if (not product.active or not product.wgs_cancellation_fee or product.recurring_invoice
                or product.company_id != company):
            raise UserError(_('Revisa la configuracion del servicio de cancelacion de esta empresa.'))
        return product

    def _wgs_cancellation_revision(self, source):
        # A later reenrollment can reproduce the exact old dates/lines. The
        # cancellation receipt supplies a durable epoch even in that case.
        return fingerprint({'source': self._wgs_source_contract(source, include_scheduled=True),
                            'last_cancellation': source.wgs_pos_cancellation_receipt or False})

    def _wgs_cancellation_taxes(self, product, company):
        # Odoo accounting shares ancestor taxes with branches. Exact company
        # equality silently drops those taxes while the native POS keeps them.
        return product.taxes_id.filtered_domain(self.env['account.tax']._check_company_domain(company))

    def _wgs_assert_cancellation_context(self, payload, *, actual_session_id=False):
        sessions = self.env['pos.session'].sudo()
        original = sessions.browse(payload['session_id']).exists()
        session = sessions.browse(actual_session_id).exists() if actual_session_id else original
        rescued = original and session != original
        if (not original or not session or session.state != 'opened'
                or (rescued and (original.state not in ('closing_control', 'closed') or session.config_id != original.config_id))
                or session.company_id.id != payload['company_id']
                or session.currency_id.id != payload['currency_id']):
            raise UserError(_('Cambio la sesion del POS. Cotiza nuevamente la cancelacion.'))
        if not payload['amount_total']:
            return
        product = self.env['product.product'].sudo().browse(payload['product_id']).exists()
        fpos = self.env['account.fiscal.position'].sudo().browse(payload['fiscal_position_id']).exists()
        if (not product or not product.active or not product.wgs_cancellation_fee or product.recurring_invoice
                or product.company_id.id != payload['company_id'] or fpos.id != payload['fiscal_position_id']):
            raise UserError(_('Cambio el servicio de cancelacion. Actualiza la cotizacion.'))
        taxes = self._wgs_cancellation_taxes(product, session.company_id)
        mapped = fpos.map_tax(taxes) if fpos else taxes
        total = mapped.compute_all(payload['ticket_charge_now'], currency=session.currency_id,
                                   product=product)['total_included']
        if (sorted(taxes.ids) != sorted(payload['tax_ids'])
                or sorted(mapped.ids) != sorted(payload['mapped_tax_ids'])
                or session.currency_id.compare_amounts(total, payload['amount_total'])):
            raise UserError(_('Cambiaron los impuestos del cargo. Actualiza la cotizacion antes de cobrar.'))

    @api.model
    def wgs_get_subscription_cancellation_quote_for_pos(self, subscription_id, amount, reason='', session_id=False,
                                                       fiscal_position_id=False):
        source = self._wgs_cancellation_source(subscription_id)
        if not source._wgs_can_cancel_for_pos():
            raise UserError(_('El paquete ya esta cerrado o cancelado.'))
        try:
            amount = float(amount)
        except (TypeError, ValueError, OverflowError) as error:
            raise UserError(_('Captura un cargo valido, mayor o igual a cero.')) from error
        if not math.isfinite(amount) or amount < 0:
            raise UserError(_('Captura un cargo valido, mayor o igual a cero.'))
        amount = source.currency_id.round(amount)
        session = self.env['pos.session'].sudo().browse(int(session_id or 0)).exists()
        if not session or session.company_id != source.company_id or session.state != 'opened':
            raise UserError(_('La cancelacion requiere una sesion POS abierta de la empresa de origen.'))
        if session.currency_id != source.currency_id:
            raise UserError(_('La moneda del POS debe coincidir con la moneda del contrato.'))
        fpos = self.env['account.fiscal.position'].sudo().browse(int(fiscal_position_id or 0)).exists()
        if fpos and fpos.company_id != source.company_id:
            raise AccessError(_('La posicion fiscal no corresponde a esta empresa.'))
        product = self._wgs_cancellation_product(source.company_id) if amount else self.env['product.product']
        taxes = self._wgs_cancellation_taxes(product, source.company_id)
        mapped = fpos.map_tax(taxes) if fpos else taxes
        price = amount
        if mapped:
            reverse = mapped._get_tax_details(amount, 1, product=product,
                                             special_mode='total_included', rounding_method='round_globally')
            price = reverse['total_excluded'] + sum(
                item['tax_amount'] for item in reverse['taxes_data'] if item['tax'].price_include
            )
        price = round(price, self.env['decimal.precision'].precision_get('Product Price'))
        total = mapped.compute_all(price, currency=source.currency_id, product=product,
                                   partner=source.partner_id)['total_included']
        if source.currency_id.compare_amounts(total, amount):
            raise UserError(_('El importe no puede representarse exactamente con los impuestos del servicio. Revisa el cargo.'))
        payload = {
            'kind': CANCELLATION_FLOW, 'nonce': str(uuid4()), 'subscription_id': source.id,
            'source_revision': self._wgs_cancellation_revision(source),
            'partner_id': source.partner_id.id, 'company_id': source.company_id.id,
            'currency_id': source.currency_id.id, 'session_id': session.id,
            'fiscal_position_id': fpos.id, 'product_id': product.id,
            'tax_ids': taxes.ids, 'mapped_tax_ids': mapped.ids,
            'amount_total': amount, 'ticket_charge_now': price, 'reason': str(reason or '').strip()[:500],
        }
        return {**payload, 'cancellation_quote': {'payload': payload, 'signature': self._wgs_quote_signature(payload)}}

    def _wgs_verify_cancellation_quote(self, snapshot, *, partner_id, company_id, subscription_id,
                                       product_id=False, check_source=True, actual_session_id=False):
        quote = snapshot.get('cancellation_quote') or {}
        payload = quote.get('payload') or {}
        signature = quote.get('signature')
        if not signature or not hmac.compare_digest(str(signature), self._wgs_quote_signature(payload)):
            raise UserError(_('La cotizacion de cancelacion cambio. Abre nuevamente Cancelar paquete.'))
        if (payload.get('kind') != CANCELLATION_FLOW or payload.get('partner_id') != partner_id
                or payload.get('company_id') != company_id or payload.get('product_id') != product_id
                or payload.get('subscription_id') != subscription_id):
            raise UserError(_('La cancelacion no corresponde al titular, empresa, paquete o cargo del ticket.'))
        source = self._wgs_cancellation_source(payload['subscription_id'], company_id=company_id)
        if check_source and (not source._wgs_can_cancel_for_pos()
                             or payload['source_revision'] != self._wgs_cancellation_revision(source)):
            raise UserError(_('El paquete cambio desde la cotizacion. Actualiza la cancelacion antes de cobrar.'))
        if check_source:
            self._wgs_assert_cancellation_context(payload, actual_session_id=actual_session_id)
        return payload, source

    def _wgs_normalize_cancellation_config(self, config, *, partner_id, company_id, check_source=True):
        payload, _source = self._wgs_verify_cancellation_quote(
            config.get('pricing_snapshot') or {}, partner_id=partner_id, company_id=company_id,
            product_id=self._wgs_to_int(config.get('product_id')),
            subscription_id=self._wgs_to_int(config.get('source_subscription_id')), check_source=check_source,
        )
        if (payload['amount_total'] <= 0 or float(config.get('quantity') or 0) != 1
                or float(config.get('discount_percent') or 0)):
            raise UserError(_('El cargo de cancelacion debe ser positivo, una unidad y sin descuento.'))
        return {**config, 'participant_ids': [partner_id], 'plan_id': False, 'pricing_id': False,
                'start_date': False, 'end_date': False,
                'pricing_snapshot': {**payload, 'cancellation_quote': config['pricing_snapshot']['cancellation_quote']}}

    def _wgs_validate_cancellation_order_context(self, config, *, session_id, fiscal_position_id):
        if config.get('flow') != CANCELLATION_FLOW:
            return
        payload = config['pricing_snapshot']
        if payload['session_id'] != session_id or payload['fiscal_position_id'] != fiscal_position_id:
            raise UserError(_('Cambio la sesion o la posicion fiscal. Cotiza nuevamente el cargo antes de cobrar.'))

    def _wgs_complete_package_cancellation(self, source, payload, *, line=False):
        """Preserve money and paid dates; stop entitlement and future activation."""
        pending = self._wgs_pending_package_changes(source)
        pending.write({'wgs_application_state': 'cancelled', 'wgs_activation_error': False})
        source._wgs_close_subscription_commercially(origin='pos_cancellation')
        if source.wgs_domiciliation_contract_id.state == 'active':
            raise UserError(_('No se confirmo la baja del contrato domiciliado.'))
        source.write({'wgs_pos_cancellation_receipt': {
            'nonce': payload['nonce'], 'amount_total': payload['amount_total'],
            'reason': payload['reason'], 'user_id': self.env.uid,
            'at': fields.Datetime.to_string(fields.Datetime.now()),
            'pos_line_id': line.id if line else False, 'cancelled_scheduled_line_ids': pending.ids,
        }})
        source.message_post(body=_('Paquete cancelado desde POS. Cargo: %(amount)s %(currency)s. Motivo: %(reason)s',
                                  amount=payload['amount_total'], currency=source.currency_id.name,
                                  reason=payload['reason'] or '-'))
        return source

    @api.model
    def wgs_cancel_subscription_without_charge_for_pos(self, snapshot):
        payload = (snapshot.get('cancellation_quote') or {}).get('payload') or {}
        source = self._wgs_cancellation_source(payload.get('subscription_id'))
        # Same lock order as checkout; Odoo owns the transaction and all locks.
        self.env.cr.execute('SELECT id FROM res_partner WHERE id = %s FOR UPDATE', [source.partner_id.id])
        self.env.cr.execute('SELECT id FROM sale_order WHERE id = %s FOR UPDATE', [source.id])
        source.invalidate_recordset()
        payload, source = self._wgs_verify_cancellation_quote(
            snapshot, partner_id=source.partner_id.id, company_id=source.company_id.id,
            subscription_id=source.id, check_source=False,
        )
        if payload['amount_total'] or payload['product_id']:
            raise UserError(_('El cargo debe pagarse en el ticket antes de cancelar el paquete.'))
        receipt = source.wgs_pos_cancellation_receipt or {}
        if receipt.get('nonce') == payload['nonce'] and not source._wgs_can_cancel_for_pos():
            return {'ok': True, 'already_applied': True, 'subscription_id': source.id}
        if payload['source_revision'] != self._wgs_cancellation_revision(source):
            raise UserError(_('El paquete cambio. Abre nuevamente la cancelacion.'))
        self._wgs_assert_cancellation_context(payload)
        affected = source._wgs_get_access_related_partner_ids()
        self._wgs_complete_package_cancellation(source.with_context(wgs_defer_access_sync=True), payload)
        source._wgs_update_access_snapshot(force=True)
        result = source.with_context(wgs_defer_access_sync=False, access_sync_priority=True)._wgs_sync_access_control_people(
            extra_partner_ids=sorted(affected),
        )
        if not isinstance(result, dict) or result.get('issues') or result.get('checked') != len(affected):
            raise UserError(_('No se pudo verificar la baja de acceso. No se aplico la cancelacion; reintenta la operacion.'))
        return {'ok': True, 'subscription_id': source.id}

    def _wgs_apply_paid_package_cancellation(self, line):
        self.ensure_one()
        payload, source = self._wgs_verify_cancellation_quote(
            json.loads(line.wgs_pricing_snapshot_json or '{}'),
            partner_id=self.partner_id.id, company_id=self.company_id.id, product_id=line.product_id.id,
            subscription_id=line.wgs_subscription_source_id.id,
            actual_session_id=self.session_id.id,
        )
        if (self.state not in ('paid', 'done', 'invoiced') or payload['amount_total'] <= 0
                or line.qty != 1 or line.discount or self.currency_id.compare_amounts(line.price_unit, payload['ticket_charge_now'])
                or self.currency_id.compare_amounts(line.price_subtotal_incl, payload['amount_total'])
                or self.fiscal_position_id.id != payload['fiscal_position_id']
                or sorted(line.tax_ids.ids) != sorted(payload['tax_ids'])
                or sorted(line.tax_ids_after_fiscal_position.ids) != sorted(payload['mapped_tax_ids'])):
            raise UserError(_('El cargo pagado no coincide con la cancelacion cotizada. No se aplico la cancelacion.'))
        return self._wgs_complete_package_cancellation(source, payload, line=line)
