from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    _INVALID_SUBSCRIPTION_STATE_TOKENS = (
        'cancel',
        'churn',
        'close',
        'draft',
        'pause',
        'upsell',
    )

    @api.model
    def get_partner_subscription_status_for_pos(self, partner_id):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('No tienes permisos para consultar vigencia desde Punto de Venta.'))

        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner:
            return {
                'partner_id': False,
                'partner_name': False,
                'today': fields.Date.context_today(self).isoformat(),
                'items': [],
                'valid_count': 0,
            }

        today = fields.Date.context_today(self)
        subscriptions = self._get_pos_subscription_orders(partner)

        items = []
        for subscription in subscriptions:
            item = subscription._build_pos_subscription_status_item(today)
            if item:
                items.append(item)

        items.sort(
            key=lambda row: (
                not row['is_valid'],
                row['valid_until'] or '9999-12-31',
                row['subscription_name'],
            )
        )

        return {
            'partner_id': partner.id,
            'partner_name': partner.display_name,
            'today': today.isoformat(),
            'items': items,
            'valid_count': sum(1 for row in items if row['is_valid']),
        }

    @api.model
    def get_partner_subscription_status_map_for_pos(self, partner_ids):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('No tienes permisos para consultar vigencia desde Punto de Venta.'))

        partner_ids = [int(pid) for pid in (partner_ids or []) if pid]
        if not partner_ids:
            return {}

        partners = self.env['res.partner'].browse(partner_ids).exists()
        if not partners:
            return {}

        today = fields.Date.context_today(self)
        subscriptions_by_partner = self._get_pos_subscription_orders_by_partners(partners)

        result = {}
        for partner in partners:
            subscriptions = subscriptions_by_partner.get(partner.id, self.browse())
            items = []
            for subscription in subscriptions:
                item = subscription._build_pos_subscription_status_item(today)
                if item:
                    items.append(item)

            valid_items = [row for row in items if row['is_valid']]
            if valid_items:
                valid_until_values = [row['valid_until'] for row in valid_items if row['valid_until']]
                nearest_valid_until = min(valid_until_values) if valid_until_values else False
                result[partner.id] = {
                    'state': 'valid',
                    'short_label': '[VIGENTE]',
                    'valid_until': nearest_valid_until,
                }
            elif items:
                result[partner.id] = {
                    'state': 'expired',
                    'short_label': '[SIN VIGENCIA]',
                    'valid_until': False,
                }
            else:
                result[partner.id] = {
                    'state': 'none',
                    'short_label': False,
                    'valid_until': False,
                }

        return result

    @api.model
    def _get_pos_subscription_orders(self, partner):
        domain = [
            '|',
            ('participant_ids', 'in', partner.id),
            ('partner_id', '=', partner.id),
            ('state', 'in', ['sale', 'done']),
        ]
        if 'is_subscription' in self._fields:
            domain.append(('is_subscription', '=', True))

        subscriptions = self.sudo().search(domain, order='id desc')
        return subscriptions.filtered(lambda order: bool(order._get_recurring_lines()))

    @api.model
    def _get_pos_subscription_orders_by_partners(self, partners):
        if not partners:
            return {}

        partner_ids = partners.ids
        domain = [
            '|',
            ('participant_ids', 'in', partner_ids),
            ('partner_id', 'in', partner_ids),
            ('state', 'in', ['sale', 'done']),
        ]
        if 'is_subscription' in self._fields:
            domain.append(('is_subscription', '=', True))

        subscriptions = self.sudo().search(domain, order='id desc')
        subscriptions = subscriptions.filtered(lambda order: bool(order._get_recurring_lines()))

        subscriptions_by_partner = {partner.id: self.browse() for partner in partners}
        partner_id_set = set(partner_ids)

        for subscription in subscriptions:
            shared_partner_ids = set(partner_id_set.intersection(subscription.participant_ids.ids))
            if subscription.partner_id and subscription.partner_id.id in partner_id_set:
                shared_partner_ids.add(subscription.partner_id.id)
            for partner_id in shared_partner_ids:
                subscriptions_by_partner[partner_id] |= subscription

        return subscriptions_by_partner

    def _build_pos_subscription_status_item(self, today):
        self.ensure_one()

        recurring_lines = self._get_recurring_lines()
        if not recurring_lines:
            return False

        is_valid = True
        reason = _('Dentro del periodo pagado.')

        start_date = self._get_first_available_date(
            ('start_date', 'date_start', 'subscription_start_date', 'date_order')
        )
        next_invoice_date = self._get_first_available_date(('recurring_next_date', 'next_invoice_date'))
        hard_end_date = self._get_first_available_date(('date_end', 'end_date'))

        period_start = False
        valid_until = False

        if next_invoice_date:
            recurrence_delta = self._get_recurrence_delta()
            period_start = next_invoice_date - recurrence_delta
            valid_until = next_invoice_date - relativedelta(days=1)

        if hard_end_date and (not valid_until or hard_end_date < valid_until):
            valid_until = hard_end_date

        if not self._is_active_subscription_state():
            is_valid = False
            reason = _('La suscripción no está en estado activo.')
        elif start_date and today < start_date:
            is_valid = False
            reason = _('La suscripción todavía no inicia.')
        elif next_invoice_date and today >= next_invoice_date:
            is_valid = False
            reason = _('Periodo vencido por falta de pago del siguiente ciclo.')
        elif valid_until and today > valid_until:
            is_valid = False
            reason = _('Periodo vencido.')
        elif not next_invoice_date and not valid_until:
            is_valid = False
            reason = _('No se pudo determinar la vigencia (sin próxima fecha de cobro).')

        return {
            'subscription_id': self.id,
            'subscription_name': self.name,
            'state': self.subscription_state if 'subscription_state' in self._fields else False,
            'package_names': sorted(set(recurring_lines.mapped('product_id.display_name'))),
            'period_start': period_start.isoformat() if period_start else False,
            'valid_until': valid_until.isoformat() if valid_until else False,
            'is_valid': is_valid,
            'status_label': _('Vigente') if is_valid else _('Sin vigencia'),
            'reason': reason,
        }

    def _get_recurring_lines(self):
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: line.product_id and line.product_id.product_tmpl_id.recurring_invoice
        )

    def _is_active_subscription_state(self):
        self.ensure_one()
        if 'subscription_state' not in self._fields:
            return True

        state_value = (self.subscription_state or '').lower()
        if not state_value:
            return True

        return not any(token in state_value for token in self._INVALID_SUBSCRIPTION_STATE_TOKENS)

    def _get_first_available_date(self, field_names):
        self.ensure_one()

        for field_name in field_names:
            if field_name not in self._fields:
                continue
            value = self[field_name]
            converted = self._to_date(value)
            if converted:
                return converted

        return False

    def _get_recurrence_delta(self):
        self.ensure_one()

        interval = 1
        unit = 'month'

        if {'recurring_interval', 'recurring_rule_type'}.issubset(self._fields):
            interval = self.recurring_interval or 1
            unit = self.recurring_rule_type or 'month'
        elif 'plan_id' in self._fields and self.plan_id:
            plan = self.plan_id
            if {'recurring_interval', 'recurring_rule_type'}.issubset(plan._fields):
                interval = plan.recurring_interval or 1
                unit = plan.recurring_rule_type or 'month'
            elif {'billing_period_value', 'billing_period_unit'}.issubset(plan._fields):
                interval = plan.billing_period_value or 1
                unit = plan.billing_period_unit or 'month'

        interval = int(interval) if interval else 1
        if interval < 1:
            interval = 1

        unit_value = (unit or 'month').lower()

        if 'day' in unit_value:
            return relativedelta(days=interval)
        if 'week' in unit_value:
            return relativedelta(weeks=interval)
        if 'year' in unit_value:
            return relativedelta(years=interval)
        return relativedelta(months=interval)

    @api.model
    def _to_date(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return fields.Date.to_date(value)
