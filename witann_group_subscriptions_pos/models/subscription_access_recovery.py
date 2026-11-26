"""POS access recovery orchestration, separate from commercial operations."""

from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    wgs_last_access_resync_id = fields.Many2one('access_control.resync_request', copy=False, readonly=True)

    @api.model
    def _wgs_access_recovery_subscription(self, subscription_id):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para recuperar acceso desde Punto de Venta.'))
        subscription = self._wgs_browse_subscription_for_pos(subscription_id)
        company = self._wgs_resolve_pos_company_for_pos(False)
        if not subscription or subscription.company_id != company or not subscription._is_subscription_record_for_pos():
            raise AccessError(_('La suscripcion debe administrarse desde el POS de su sede de origen.'))
        return subscription

    @api.model
    def _wgs_request_access_recovery(self, subscription_id, device_id=False):
        subscription = self._wgs_access_recovery_subscription(subscription_id)
        partner_ids = sorted(subscription._wgs_get_access_related_partner_ids())
        if partner_ids:
            self.env.cr.execute('SELECT id FROM res_partner WHERE id = ANY(%s) ORDER BY id FOR UPDATE', [partner_ids])
        self.env.cr.execute('SELECT id FROM sale_order WHERE id = %s FOR UPDATE', [subscription.id])
        subscription.invalidate_recordset()
        if sorted(subscription._wgs_get_access_related_partner_ids()) != partner_ids:
            raise UserError(_('Los participantes cambiaron; vuelve a abrir la recuperacion de acceso.'))
        previous = subscription.wgs_last_access_resync_id
        now = fields.Datetime.now()
        if previous and (now - previous.create_date).total_seconds() < self._WGS_POS_ACCESS_RESYNC_COOLDOWN_SECONDS:
            raise UserError(_('Espera un minuto antes de solicitar otra recuperacion. Puedes consultar el estado de la anterior.'))
        device_domain = [('active', '=', True), ('site_id', 'in', subscription._wgs_get_access_site_ids())]
        devices = self.env['access_control.device'].sudo().search(device_domain)
        if device_id:
            try:
                selected_id = int(device_id)
            except (TypeError, ValueError):
                raise UserError(_('Selecciona un equipo valido.'))
            selected = devices.filtered(lambda device: device.id == selected_id)
            if not selected:
                raise AccessError(_('El equipo seleccionado no corresponde a los sitios autorizados por esta membresia.'))
            devices = selected
        if not devices:
            raise UserError(_('No hay equipos activos para los sitios de esta membresia.'))

        # Re-evaluate existing policy; never change dates, plans, prices or payments.
        subscription.with_context(access_sync_priority=True)._wgs_sync_access_control_people()
        people = self._wgs_person_model_for_pos().search([
            ('partner_id', 'in', sorted(subscription._wgs_get_access_related_partner_ids())),
            ('active', '=', True), ('access_state', '=', 'enabled'), ('global_user_id', '!=', False),
        ])
        if not people:
            raise UserError(_('La membresia no tiene acceso vigente habilitado. La recuperacion no autoriza accesos vencidos o bloqueados.'))
        end = subscription._wgs_get_subscription_access_period()['valid_until']
        authorization_expires_at = False
        if end:
            local_midnight = subscription._wgs_get_subscription_business_timezone().localize(
                datetime.combine(end + timedelta(days=1), time.min))
            authorization_expires_at = local_midnight.astimezone(pytz.UTC).replace(tzinfo=None)
        request = self.env['access_control.resync_request'].sudo()._queue_for_people(
            people, devices, subscription.company_id, self.env.user,
            authorization_expires_at=authorization_expires_at,
        )
        subscription.write({'wgs_last_access_resync_id': request.id})
        return {'ok': True, 'subscription_id': subscription.id,
                'access_summary': subscription._wgs_get_access_people_summary_for_pos(),
                'recovery': request._status_payload(),
                'cooldown_seconds': self._WGS_POS_ACCESS_RESYNC_COOLDOWN_SECONDS}

    @api.model
    def wgs_get_access_recovery_status_for_pos(self, subscription_id):
        subscription = self._wgs_access_recovery_subscription(subscription_id)
        request = subscription.wgs_last_access_resync_id
        return request._status_payload(refresh=True) if request else {'state': 'none', 'targets': []}

    @api.model
    def _wgs_add_access_recovery_detail(self, items, subscriptions):
        by_id = {subscription.id: subscription for subscription in subscriptions}
        for item in items:
            subscription = by_id[item['subscription_id']]
            request = subscription.wgs_last_access_resync_id
            item['access_recovery'] = request._status_payload() if request else False
