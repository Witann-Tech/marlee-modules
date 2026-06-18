from odoo import api, models


class WgsSubscriptionPosSyncService(models.AbstractModel):
    _name = 'wgs.subscription.pos.sync.service'
    _description = 'Servicio técnico de auditoría y reparación de ventas POS de suscripción'

    @api.model
    def _audit_paid_subscription_pos_sync_issues(self, date_from=False, date_to=False, limit=5000):
        return self.env['pos.order']._wgs_audit_paid_subscription_pos_sync_issues(
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    @api.model
    def _repair_paid_subscription_pos_sync_issues(self, date_from=False, date_to=False, limit=5000, dry_run=True):
        return self.env['pos.order']._wgs_repair_paid_subscription_pos_sync_issues(
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            dry_run=dry_run,
        )

    @api.model
    def _repair_paid_subscription_pos_line_ids(self, line_ids, options_by_line=False, dry_run=True):
        return self.env['pos.order']._wgs_repair_paid_subscription_pos_line_ids(
            line_ids,
            options_by_line=options_by_line,
            dry_run=dry_run,
        )
