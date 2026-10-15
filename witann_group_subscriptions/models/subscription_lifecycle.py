"""Keep native automatic billing/closing out of WGS-managed contracts.

Ownership is derived from the authoritative access/contract data. POS extends
the same predicate with paid operation links. No additional balance or global
ir.cron switch is used. Manual native actions retain their normal path.
"""

from odoo import api, models
from odoo.fields import Domain


class SaleOrderWgsLifecycle(models.Model):
    _inherit = 'sale.order'

    _WGS_NATIVE_LIFECYCLE_CONTEXT_KEY = 'wgs_native_subscription_lifecycle'

    @api.model
    def _wgs_managed_subscription_domain(self):
        return (
            Domain('wgs_access_site_ids', '!=', False)
            | Domain('wgs_domiciliation_contract_id', '!=', False)
        )

    @api.model
    def _wgs_native_subscription_domain(self):
        return ~self._wgs_managed_subscription_domain()

    @api.model
    def _cron_recurring_create_invoice(self):
        native = self.with_context(**{self._WGS_NATIVE_LIFECYCLE_CONTEXT_KEY: True})
        return super(SaleOrderWgsLifecycle, native)._cron_recurring_create_invoice()

    @api.model
    def _cron_subscription_expiration(self):
        native = self.with_context(**{self._WGS_NATIVE_LIFECYCLE_CONTEXT_KEY: True})
        return super(SaleOrderWgsLifecycle, native)._cron_subscription_expiration()

    @api.model
    def _cron_recurring_send_payment_reminder(self):
        native = self.with_context(**{self._WGS_NATIVE_LIFECYCLE_CONTEXT_KEY: True})
        return super(SaleOrderWgsLifecycle, native)._cron_recurring_send_payment_reminder()

    def _search(self, domain, *args, **kwargs):
        # Native expiration has no domain hook and unions raw-SQL candidates.
        # Scope only automatic jobs, before LIMIT; never alter ordinary UI reads.
        if self.env.context.get(self._WGS_NATIVE_LIFECYCLE_CONTEXT_KEY):
            domain = Domain(domain) & self._wgs_native_subscription_domain()
        return super()._search(domain, *args, **kwargs)

    def _recurring_invoice_domain(self, extra_domain=None):
        domain = super()._recurring_invoice_domain(extra_domain=extra_domain)
        return Domain(domain) & self._wgs_native_subscription_domain()

    def _recurring_invoice_get_subscriptions(self, grouped=False, batch_size=30):
        native = self
        if self.env.context.get(self._WGS_NATIVE_LIFECYCLE_CONTEXT_KEY) and self:
            native = self.filtered_domain(self._wgs_native_subscription_domain())
            if not native:
                # In core an empty self means "select all", not "no candidates".
                return [], False
        return super(SaleOrderWgsLifecycle, native)._recurring_invoice_get_subscriptions(
            grouped=grouped, batch_size=batch_size,
        )

    def _subscription_reminder_parameters(self):
        parameters = super()._subscription_reminder_parameters()
        if parameters:
            parameters = {**parameters, 'domain': Domain(parameters['domain']) & self._wgs_native_subscription_domain()}
        return parameters

    def _wgs_filter_native_expiration_rows(self, rows):
        if not rows or not self.env.context.get(self._WGS_NATIVE_LIFECYCLE_CONTEXT_KEY):
            return rows
        ids = [row['so_id'] for row in rows]
        native_ids = set(self.search(
            Domain('id', 'in', ids) & self._wgs_native_subscription_domain(),
        ).ids)
        return [row for row in rows if row['so_id'] in native_ids]

    def _get_expired_subscriptions(self):
        return self._wgs_filter_native_expiration_rows(super()._get_expired_subscriptions())

    def _get_unpaid_subscriptions(self):
        return self._wgs_filter_native_expiration_rows(super()._get_unpaid_subscriptions())

    def _subscription_auto_close(self):
        native = self.filtered_domain(self._wgs_native_subscription_domain())
        if not native:
            return native
        return super(SaleOrderWgsLifecycle, native)._subscription_auto_close()

    def set_close(self, close_reason_id=None, renew=False):
        native = self
        if self.env.context.get(self._WGS_NATIVE_LIFECYCLE_CONTEXT_KEY):
            # Defense for explicit browse() batches inside native automation.
            native = self.filtered_domain(self._wgs_native_subscription_domain())
            if not native:
                return True
        return super(SaleOrderWgsLifecycle, native).set_close(close_reason_id=close_reason_id, renew=renew)
