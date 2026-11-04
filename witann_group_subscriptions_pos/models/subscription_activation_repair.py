"""Explicit recovery of a paid change whose historical source has diverged."""

import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..subscription_contract import fingerprint


class PosSubscriptionActivationRepair(models.Model):
    _inherit = 'pos.order'

    def _wgs_prepare_paid_activation_repair(self, line):
        order = line.order_id
        source = line.wgs_subscription_source_id
        if (order.state not in ('paid', 'done', 'invoiced') or line.qty <= 0
                or line.wgs_subscription_flow != 'renewal' or not source
                or line.wgs_application_state not in ('scheduled', 'review')
                or source.company_id != order.company_id or source.partner_id != order.partner_id
                or source.wgs_domiciliation_contract_id
                or not line.wgs_application_date
                or line.wgs_application_date > self._wgs_get_subscription_business_today_for_pos(company=order.company_id)):
            raise UserError(_('Selecciona un cambio no domiciliado pagado, exigible y pendiente del mismo titular.'))
        if fingerprint(order._wgs_line_operation_input(line)) != line.wgs_application_hash:
            raise UserError(_('El contenido del pago original cambio; no es seguro recuperar su activacion.'))
        snapshot = json.loads(line.wgs_pricing_snapshot_json or '{}')
        payload = order._wgs_verify_commercial_quote(
            snapshot, product_id=line.product_id.id, partner_id=order.partner_id.id,
            company_id=order.company_id.id, flow='renewal', source_id=source.id,
        )
        if order._wgs_pending_package_changes(source)[:1] != line:
            raise UserError(_('Primero debe resolverse el cambio pagado anterior de esta suscripcion.'))
        if order._wgs_find_later_paid_subscription_line_for_same_subscription_customer(line):
            raise UserError(_('Existe un pago posterior; no se puede sustituir su vigencia desde esta recuperacion.'))
        if self.env['pos.order.line'].sudo().search_count([
            ('qty', '<', 0), ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
            '|', ('refunded_orderline_id', '=', line.id),
            ('wgs_subscription_refund_origin_line_id', '=', line.id),
        ]):
            raise UserError(_('El pago ya fue devuelto; no se puede recuperar su activacion.'))
        return {
            'line_id': line.id, 'order_id': order.id, 'ticket': order.pos_reference,
            'subscription_id': source.id, 'company_id': order.company_id.id,
            'partner_id': order.partner_id.id, 'payment_hash': line.wgs_application_hash,
            'payment': {
                'total': order.amount_total, 'paid': order.amount_paid,
                'currency': order.currency_id.id,
                'entries': [(item.id, item.amount, item.payment_method_id.id,
                             fields.Datetime.to_string(item.payment_date))
                            for item in order.payment_ids.sorted('id')],
            },
            'source_contract': order._wgs_source_contract(source),
            'activation_revision': line.wgs_activation_revision,
            'paid_period': payload['pricing'],
        }

    @api.model
    def wgs_recover_paid_activation_for_pos(self, line_id, approval_digest=False, dry_run=True):
        if (not self.env.user.has_group('point_of_sale.group_pos_manager')
                or not self.env.user.has_group('base.group_system')):
            raise UserError(_('La recuperacion historica requiere un administrador responsable POS.'))
        line = self.env['pos.order.line'].sudo().browse(int(line_id)).exists()
        if not line:
            raise UserError(_('La linea pagada no existe.'))
        line.order_id.with_user(self.env.user).check_access('write')
        order = line.order_id
        if dry_run:
            proposal = order._wgs_prepare_paid_activation_repair(line)
            return {'proposal': proposal, 'approval_digest': fingerprint(proposal)}
        with self.env.cr.savepoint():
            order._wgs_lock_operation_records(line)
            proposal = order._wgs_prepare_paid_activation_repair(line)
            if approval_digest != fingerprint(proposal):
                raise UserError(_('La propuesta cambio. Repite el dry_run y aprueba el estado actual.'))
            source = line.wgs_subscription_source_id
            if source._wgs_get_subscription_state_category() in ('closed', 'cancel'):
                if source.state == 'cancel':
                    raise UserError(_('Una venta cancelada requiere revisar su cancelacion, no reabrirla automaticamente.'))
                order.with_context(wgs_defer_access_sync=True)._wgs_reactivate_subscription_order_for_pos(source)
            line.write({
                'wgs_activation_revision': order._wgs_source_revision(source),
                'wgs_activation_contract': order._wgs_source_contract(source),
                'wgs_activation_retry_at': False,
            })
            if not order._wgs_activate_package_change(line):
                raise UserError(_('No se recupero la compra pagada: %s') % line.wgs_activation_error)
            receipt = line.wgs_application_receipt or {}
            line.write({'wgs_application_receipt': {**receipt, 'approved_recovery': {
                'digest': approval_digest, 'operator_id': self.env.uid,
                'at': fields.Datetime.to_string(fields.Datetime.now()),
                'previous_source': proposal['source_contract'],
            }}})
            source.message_post(body=_('Activacion historica del pago %(ticket)s recuperada con aprobacion %(digest)s; sin nuevos cobros.') % {
                'ticket': order.pos_reference, 'digest': approval_digest,
            })
            return {'line_id': line.id, 'subscription_id': source.id, 'state': line.wgs_application_state}
