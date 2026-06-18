from odoo import api, models


class WgsSubscriptionAccessService(models.AbstractModel):
    _name = 'wgs.subscription.access.service'
    _description = 'Servicio técnico de operaciones de acceso de suscripciones'

    @api.model
    def _block_partner_access(self, partner_id, reason, company_id=False):
        return self.env['sale.order']._wgs_block_partner_access_from_service(
            partner_id,
            reason,
            company_id=company_id,
        )

    @api.model
    def _unblock_partner_access(self, partner_id, company_id=False):
        return self.env['sale.order']._wgs_unblock_partner_access_from_service(
            partner_id,
            company_id=company_id,
        )

    @api.model
    def _open_access_door(self, device_id, options=False):
        return self.env['sale.order']._wgs_open_access_door_from_service(device_id, options or {})

    @api.model
    def _grant_external_access(self, partner_id, provider, options=False):
        return self.env['sale.order']._wgs_grant_external_access_from_service(
            partner_id,
            provider,
            options or {},
        )

    @api.model
    def _resync_subscription_access(self, subscription_id):
        return self.env['sale.order']._wgs_resync_subscription_access_from_service(subscription_id)
