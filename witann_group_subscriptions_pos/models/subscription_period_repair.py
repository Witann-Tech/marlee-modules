"""Explicit, reviewable historical period corrections; never replay a sale."""

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..subscription_contract import fingerprint, validate_period


class SubscriptionPeriodRepair(models.Model):
    _inherit = 'pos.order'

    def _wgs_period_repair_digest(self, proposal):
        return fingerprint(proposal)

    def _wgs_prepare_period_repair(self, line, options):
        source = self._wgs_resolve_targeted_subscription_repair_source(line, options) or line.wgs_sale_order_id
        if not source or source.company_id != line.order_id.company_id:
            raise UserError(_('Especifica la suscripcion y empresa correctas para la reparacion.'))
        if source.partner_id != line.order_id.partner_id:
            raise UserError(_('La reparacion no puede cambiar el titular historico.'))
        if source.wgs_domiciliation_contract_id:
            raise UserError(_('La cartera domiciliada requiere revision de cuotas, no una correccion de fechas.'))
        if self._wgs_find_later_paid_subscription_line_for_same_subscription_customer(line):
            raise UserError(_('Existe otro pago posterior; revisa la cronologia completa antes de corregir.'))
        if self.env['pos.order.line'].search_count([
            ('qty', '<', 0),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
            '|', ('refunded_orderline_id', '=', line.id),
            ('wgs_subscription_refund_origin_line_id', '=', line.id),
        ]):
            raise UserError(_('El pago fue reembolsado; no se puede restaurar su periodo.'))
        plan = self.env['sale.subscription.plan'].browse(int(options.get('plan_id') or 0)).exists()
        if not plan or plan.wgs_domiciliation_enabled:
            raise UserError(_('Selecciona explicitamente el plan historico contratado no domiciliado.'))
        start = fields.Date.to_date(options.get('start_date'))
        if not start:
            raise UserError(_('Confirma el inicio historico; no se usara el dia de la reparacion.'))
        end, next_date, single_day = self._wgs_normalize_subscription_period_for_pos(
            product=line.product_id, plan_record=plan, subscription_start_date=start,
        )
        if options.get('end_date') and fields.Date.to_date(options['end_date']) != end:
            raise UserError(_('El fin propuesto no concuerda con el inicio y plazo contratado.'))
        return {
            'line_id': line.id, 'subscription_id': source.id, 'company_id': source.company_id.id,
            'source_revision': self._wgs_source_revision(source),
            'payment_date': fields.Datetime.to_string(line.order_id.date_order),
            'payment_fingerprint': fingerprint(line.order_id._wgs_line_operation_input(line)),
            'product_id': line.product_id.id, 'plan_id': plan.id,
            'start_date': start.isoformat(), 'end_date': end.isoformat(),
            'next_date': next_date.isoformat() if next_date else False,
            'single_day': single_day,
        }

    def _wgs_apply_approved_period_repair(self, line, options):
        source = self._wgs_resolve_targeted_subscription_repair_source(line, options) or line.wgs_sale_order_id
        # Use the same lock order as sales/refunds, including an unlinked target.
        line.order_id._wgs_lock_operation_records(line)
        source.flush_recordset()
        self.env.cr.execute('SELECT id FROM sale_order WHERE id = ANY(%s) ORDER BY id FOR UPDATE', [source.ids])
        source.invalidate_recordset()
        proposal = self._wgs_prepare_period_repair(line, options)
        if options.get('approval_digest') != self._wgs_period_repair_digest(proposal):
            raise UserError(_('Ejecuta dry_run y aprueba su digest. La suscripcion o el pago pudieron cambiar.'))
        validate_period(proposal['start_date'], proposal['end_date'], proposal['next_date'])
        affected = source._wgs_get_access_related_partner_ids()
        scoped = line.order_id.with_context(wgs_defer_access_sync=True)
        target = source.with_env(scoped.env)
        recurring = target.order_line.filtered(lambda item: item.product_uom_qty > 0 and item.product_id.recurring_invoice)
        if len(recurring) != 1 or recurring.product_id != line.product_id:
            raise UserError(_('El paquete actual difiere del pago; requiere revision de la sustitucion, no solo fechas.'))
        scoped._wgs_sync_subscription_metadata(
            sale_order=target, subscription_start_date=fields.Date.to_date(proposal['start_date']),
            subscription_end_date=fields.Date.to_date(proposal['end_date']),
            next_billing_date=fields.Date.to_date(proposal['next_date']),
            clear_next_billing_date=proposal['single_day'], recurring_plan_id=proposal['plan_id'],
        )
        scoped._wgs_reactivate_subscription_order_for_pos(target)
        today = scoped._wgs_get_subscription_business_today_for_pos(company=target.company_id)
        if target._wgs_is_due_for_subscription_auto_close(today=today):
            target._wgs_close_subscription_for_auto_close(today=today)
        line.wgs_sale_order_id = target.id
        target.message_post(body=_('Correccion historica aprobada: %s') % str(proposal))
        source._wgs_update_access_snapshot(force=True)
        source.with_context(wgs_defer_access_sync=False, access_sync_priority=True)._wgs_sync_access_control_people(extra_partner_ids=affected)
        return source
