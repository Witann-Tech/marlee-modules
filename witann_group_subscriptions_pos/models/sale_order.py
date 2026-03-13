import logging
from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.osv import expression
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'
    _DEFAULT_PAYMENT_WINDOW_DAYS = 5

    _INVALID_SUBSCRIPTION_STATE_TOKENS = (
        'cancel',
        'churn',
        'close',
        'draft',
        'pause',
        'upsell',
    )
    _PARTNER_GENDER_FIELD_CANDIDATES = (
        'gender',
        'x_gender',
        'x_studio_gender',
        'x_studio_genero',
    )
    _PARTNER_BIRTHDAY_FIELD_CANDIDATES = (
        'birthday',
        'birthdate_date',
        'date_of_birth',
        'x_birthday',
        'x_studio_birthday',
        'x_studio_cumpleanos',
        'x_studio_fecha_nacimiento',
    )
    _PARTNER_LAST_ACCESS_FIELD_CANDIDATES = (
        'last_access_date',
        'last_access_datetime',
        'x_last_access_date',
        'x_last_access_datetime',
        'x_studio_last_access',
        'x_studio_ultimo_acceso',
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

        partners = self.env['res.partner'].sudo().with_context(active_test=False).browse(partner_ids).exists()
        if not partners:
            return {}

        today = fields.Date.context_today(self)
        subscriptions_by_partner = self._get_pos_subscription_orders_by_partners(partners)
        try:
            access_last_map = self._get_access_person_last_access_map_for_pos(partners)
        except Exception as error:
            _logger.warning('WGS POS: fallback without access last map (%s)', error)
            access_last_map = {}

        result = {}
        for partner in partners:
            subscriptions = subscriptions_by_partner.get(partner.id, self.browse())
            items = []
            for subscription in subscriptions:
                try:
                    item = subscription._build_pos_subscription_status_item(today)
                except Exception as error:
                    _logger.warning(
                        'WGS POS: could not build subscription status item (so=%s, partner=%s, error=%s)',
                        subscription.id,
                        partner.id,
                        error,
                    )
                    item = False
                if item:
                    items.append(item)

            summary = self._summarize_partner_subscription_items_for_pos(items)
            try:
                birthday_value = self._get_partner_field_value_for_pos(
                    partner,
                    self._PARTNER_BIRTHDAY_FIELD_CANDIDATES,
                )
            except Exception as error:
                _logger.warning('WGS POS: birthday fallback for partner %s (%s)', partner.id, error)
                birthday_value = False
            try:
                gender_value = self._get_partner_field_value_for_pos(
                    partner,
                    self._PARTNER_GENDER_FIELD_CANDIDATES,
                )
            except Exception as error:
                _logger.warning('WGS POS: gender fallback for partner %s (%s)', partner.id, error)
                gender_value = False
            try:
                last_access_value = self._get_partner_field_value_for_pos(
                    partner,
                    self._PARTNER_LAST_ACCESS_FIELD_CANDIDATES,
                )
            except Exception as error:
                _logger.warning('WGS POS: partner last access fallback for partner %s (%s)', partner.id, error)
                last_access_value = False
            if not last_access_value:
                last_access_value = access_last_map.get(partner.id)
            phone_value = self._get_partner_field_value_for_pos(
                partner,
                ('phone', 'mobile'),
            )
            email_value = self._get_partner_field_value_for_pos(
                partner,
                ('email',),
            )

            result[partner.id] = {
                'state': summary.get('state') or 'none',
                'short_label': summary.get('short_label') or False,
                'valid_until': summary.get('valid_until') or False,
                'start_date': summary.get('start_date') or False,
                'next_invoice_date': summary.get('next_invoice_date') or False,
                'days_to_due': summary.get('days_to_due'),
                'payment_status': summary.get('payment_status') or 'none',
                'payment_status_label': summary.get('payment_status_label') or False,
                'can_charge_renewal': bool(summary.get('can_charge_renewal')),
                'subscription_id': summary.get('subscription_id') or False,
                'package_label': summary.get('package_label') or False,
                'package_names': summary.get('package_names') or [],
                'plan_name': summary.get('plan_name') or False,
                'reason': summary.get('reason') or False,
                'subscription_name': summary.get('subscription_name') or False,
                'renewal_product_id': summary.get('renewal_product_id') or False,
                'renewal_product_name': summary.get('renewal_product_name') or False,
                'renewal_plan_id': summary.get('renewal_plan_id') or False,
                'renewal_pricing_id': summary.get('renewal_pricing_id') or False,
                'renewal_amount': summary.get('renewal_amount') or 0.0,
                'partner_name': partner.display_name,
                'phone': phone_value or False,
                'email': email_value or False,
                'gender': gender_value or False,
                'birthday': birthday_value or False,
                'last_access': last_access_value or False,
                'image_url': '/web/image/res.partner/%s/image_128' % partner.id,
            }

        return result

    @api.model
    def get_partner_directory_rows_for_pos(self, offset=0, limit=500):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('No tienes permisos para consultar vigencia desde Punto de Venta.'))

        try:
            offset = int(offset or 0)
        except (TypeError, ValueError):
            offset = 0
        try:
            limit = int(limit or 500)
        except (TypeError, ValueError):
            limit = 500
        if limit < 1:
            limit = 500

        partners = self.env['res.partner'].sudo().with_context(active_test=False).search(
            [],
            order='name asc, id asc',
            offset=max(offset, 0),
            limit=limit,
        )
        if not partners:
            return []

        try:
            status_map = self.get_partner_subscription_status_map_for_pos(partners.ids)
        except Exception as error:
            _logger.warning('WGS POS: could not build partner status map for directory batch offset=%s limit=%s (%s)', offset, limit, error)
            status_map = {}
        rows = []
        for partner in partners:
            status = status_map.get(partner.id, {})
            phone_fallback = False
            if 'phone' in partner._fields:
                phone_fallback = partner.phone or False
            rows.append({
                'id': partner.id,
                'name': status.get('partner_name') or partner.display_name,
                'email': status.get('email') or partner.email or False,
                'phone': status.get('phone') or phone_fallback,
                'state': status.get('state') or 'none',
                'payment_status': status.get('payment_status') or 'none',
                'payment_status_label': status.get('payment_status_label') or False,
                'package_label': status.get('package_label') or False,
                'plan_name': status.get('plan_name') or False,
                'start_date': status.get('start_date') or False,
                'valid_until': status.get('valid_until') or False,
                'birthday': status.get('birthday') or False,
                'gender': status.get('gender') or False,
                'last_access': status.get('last_access') or False,
                'image_url': status.get('image_url') or ('/web/image/res.partner/%s/image_128' % partner.id),
            })
        return rows

    def _summarize_partner_subscription_items_for_pos(self, items):
        if not items:
            return {
                'state': 'none',
                'short_label': False,
                'valid_until': False,
                'start_date': False,
                'next_invoice_date': False,
                'days_to_due': False,
                'payment_status': 'none',
                'payment_status_label': False,
                'can_charge_renewal': False,
                'subscription_id': False,
                'package_label': False,
                'package_names': [],
                'plan_name': False,
                'reason': False,
                'subscription_name': False,
                'renewal_product_id': False,
                'renewal_product_name': False,
                'renewal_plan_id': False,
                'renewal_pricing_id': False,
                'renewal_amount': 0.0,
            }

        valid_items = [row for row in items if row.get('is_valid')]
        if valid_items:
            prioritized = sorted(
                valid_items,
                key=lambda row: (
                    row.get('valid_until') or '9999-12-31',
                    row.get('start_date') or row.get('period_start') or '9999-12-31',
                    row.get('subscription_name') or '',
                ),
            )
            state = 'valid'
            short_label = '[VIGENTE]'
            package_source_items = valid_items
        else:
            prioritized = sorted(
                items,
                key=lambda row: (
                    row.get('valid_until') or '',
                    row.get('start_date') or row.get('period_start') or '',
                    row.get('subscription_name') or '',
                ),
                reverse=True,
            )
            state = 'expired'
            short_label = '[SIN VIGENCIA]'
            package_source_items = prioritized[:1]

        primary = prioritized[0]
        package_names = sorted(
            {
                package_name
                for row in package_source_items
                for package_name in (row.get('package_names') or [])
                if package_name
            }
        )
        package_label = ', '.join(package_names) if package_names else False

        return {
            'state': state,
            'short_label': short_label,
            'valid_until': primary.get('valid_until') or False,
            'start_date': primary.get('start_date') or primary.get('period_start') or False,
            'next_invoice_date': primary.get('next_invoice_date') or False,
            'days_to_due': primary.get('days_to_due'),
            'payment_status': primary.get('payment_status') or 'none',
            'payment_status_label': primary.get('payment_status_label') or False,
            'can_charge_renewal': bool(primary.get('can_charge_renewal')),
            'subscription_id': primary.get('subscription_id') or False,
            'package_label': package_label,
            'package_names': package_names,
            'plan_name': primary.get('plan_name') or False,
            'reason': primary.get('reason') or False,
            'subscription_name': primary.get('subscription_name') or False,
            'renewal_product_id': primary.get('renewal_product_id') or False,
            'renewal_product_name': primary.get('renewal_product_name') or False,
            'renewal_plan_id': primary.get('renewal_plan_id') or False,
            'renewal_pricing_id': primary.get('renewal_pricing_id') or False,
            'renewal_amount': primary.get('renewal_amount') or 0.0,
        }

    @api.model
    def _get_pos_subscription_orders(self, partner):
        partner_domain = [
            '|',
            ('participant_ids', 'in', partner.id),
            ('partner_id', '=', partner.id),
        ]
        domain = expression.AND([
            self._get_subscription_action_domain_for_pos(),
            partner_domain,
        ])

        subscriptions = self.sudo().search(domain, order='id desc')
        return subscriptions.filtered(lambda order: order._is_subscription_record_for_pos())

    @api.model
    def _get_pos_subscription_orders_by_partners(self, partners):
        if not partners:
            return {}

        partner_ids = partners.ids
        partner_domain = [
            '|',
            ('participant_ids', 'in', partner_ids),
            ('partner_id', 'in', partner_ids),
        ]
        domain = expression.AND([
            self._get_subscription_action_domain_for_pos(),
            partner_domain,
        ])

        subscriptions = self.sudo().search(domain, order='id desc')
        subscriptions = subscriptions.filtered(lambda order: order._is_subscription_record_for_pos())

        subscriptions_by_partner = {partner.id: self.browse() for partner in partners}
        partner_id_set = set(partner_ids)

        for subscription in subscriptions:
            shared_partner_ids = set(partner_id_set.intersection(subscription.participant_ids.ids))
            if subscription.partner_id and subscription.partner_id.id in partner_id_set:
                shared_partner_ids.add(subscription.partner_id.id)
            for partner_id in shared_partner_ids:
                subscriptions_by_partner[partner_id] |= subscription

        return subscriptions_by_partner

    @api.model
    def _get_subscription_action_domain_for_pos(self):
        base_domain = [('state', 'in', ['sale', 'done'])]
        if 'company_id' in self._fields:
            base_domain.append(('company_id', '=', self.env.company.id))

        action_domain = []
        action = self._find_subscription_action_for_pos()
        if action:
            action_domain = self._parse_action_domain_for_pos(action.domain)

        if action_domain:
            return expression.AND([base_domain, action_domain])
        return base_domain

    @api.model
    def _find_subscription_action_for_pos(self):
        xmlid_candidates = (
            'sale_subscription.sale_order_action_subscriptions',
            'sale_subscription.sale_subscription_action',
            'sale_subscription.sale_order_action_subscription',
        )
        for xmlid in xmlid_candidates:
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if action and getattr(action, 'res_model', '') == 'sale.order':
                return action

        return self.env['ir.actions.act_window'].sudo().search(
            [
                ('res_model', '=', 'sale.order'),
                ('domain', 'ilike', 'subscription'),
            ],
            order='id desc',
            limit=1,
        )

    @api.model
    def _parse_action_domain_for_pos(self, domain_value):
        if not domain_value:
            return []
        if isinstance(domain_value, (list, tuple)):
            return list(domain_value)

        if isinstance(domain_value, str):
            try:
                parsed = safe_eval(
                    domain_value,
                    {
                        'uid': self.env.uid,
                        'user': self.env.user,
                        'context': dict(self.env.context),
                    },
                )
            except Exception as error:
                _logger.warning('WGS POS: could not parse subscription action domain (%s)', error)
                return []
            return list(parsed) if isinstance(parsed, (list, tuple)) else []

        return []

    def _is_subscription_record_for_pos(self):
        self.ensure_one()
        recurring_lines = self._get_recurring_lines()
        if not recurring_lines:
            return False

        # Source of truth: records that Odoo itself classifies as subscriptions.
        if 'is_subscription' in self._fields and not self.is_subscription:
            return False
        if 'subscription_state' in self._fields:
            return bool((self.subscription_state or '').strip())
        if 'is_subscription' in self._fields:
            return True
        return False

    def _build_pos_subscription_status_item(self, today):
        self.ensure_one()

        recurring_lines = self._get_recurring_lines()
        if not recurring_lines:
            return False

        is_valid = True
        reason = _('Dentro del periodo pagado.')
        plan_name = self._get_subscription_plan_name_for_pos(recurring_lines)
        active_state = self._is_active_subscription_state()

        start_date = self._get_first_available_date(
            ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date', 'date_order')
        )
        next_invoice_date = self._get_first_available_date(('recurring_next_date', 'next_invoice_date'))
        hard_end_date = self._get_first_available_date(('date_end', 'end_date'))

        recurrence_delta = self._get_recurrence_delta()
        # POS flow treats the first period as paid at checkout. When Odoo still has
        # next invoice unset (or equal to start date), infer the next cycle boundary.
        if start_date and (not next_invoice_date or next_invoice_date <= start_date):
            next_invoice_date = start_date + recurrence_delta

        period_start = False
        valid_until = False

        if next_invoice_date:
            period_start = next_invoice_date - recurrence_delta
            valid_until = next_invoice_date - relativedelta(days=1)

        if hard_end_date and (not valid_until or hard_end_date < valid_until):
            valid_until = hard_end_date

        if not active_state:
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

        days_to_due = False
        if next_invoice_date:
            days_to_due = (next_invoice_date - today).days

        payment_status = 'none'
        payment_status_label = _('Sin ciclo')
        payment_window_days = self._get_pos_payment_window_days()
        if not active_state:
            payment_status = 'inactive'
            payment_status_label = _('Suscripción inactiva')
        elif start_date and today < start_date:
            payment_status = 'future'
            payment_status_label = _('Inicio futuro')
        elif not next_invoice_date:
            payment_status = 'unknown'
            payment_status_label = _('Sin próxima fecha')
        elif days_to_due < 0:
            payment_status = 'overdue'
            payment_status_label = _('Pago vencido')
        elif days_to_due <= payment_window_days:
            payment_status = 'window'
            payment_status_label = _('Ventana de cobro')
        else:
            payment_status = 'up_to_date'
            payment_status_label = _('Al corriente')

        recurring_total = 0.0
        for recurring_line in recurring_lines:
            qty = abs(self._get_recurring_line_qty_for_pos(recurring_line))
            discount = float(recurring_line.discount or 0.0) if 'discount' in recurring_line._fields else 0.0
            recurring_total += qty * float(recurring_line.price_unit or 0.0) * (1 - (discount / 100.0))
        recurring_total = round(max(recurring_total, 0.0), 2)

        renewal_line = recurring_lines.sorted(key=lambda line: line.id)[:1]
        renewal_product = renewal_line.product_id if renewal_line else False
        renewal_plan_id, renewal_pricing_id = self._extract_recurring_line_plan_pricing_for_pos(renewal_line)
        can_charge_renewal = bool(
            active_state
            and renewal_product
            and next_invoice_date
            and not (start_date and today < start_date)
        )

        return {
            'subscription_id': self.id,
            'subscription_name': self.name,
            'state': self.subscription_state if 'subscription_state' in self._fields else False,
            'package_names': sorted(set(recurring_lines.mapped('product_id.display_name'))),
            'plan_name': plan_name,
            'start_date': start_date.isoformat() if start_date else False,
            'period_start': period_start.isoformat() if period_start else False,
            'valid_until': valid_until.isoformat() if valid_until else False,
            'next_invoice_date': next_invoice_date.isoformat() if next_invoice_date else False,
            'days_to_due': days_to_due,
            'payment_status': payment_status,
            'payment_status_label': payment_status_label,
            'can_charge_renewal': can_charge_renewal,
            'renewal_product_id': renewal_product.id if renewal_product else False,
            'renewal_product_name': renewal_product.display_name if renewal_product else False,
            'renewal_plan_id': renewal_plan_id or False,
            'renewal_pricing_id': renewal_pricing_id or False,
            'renewal_amount': recurring_total,
            'is_valid': is_valid,
            'status_label': _('Vigente') if is_valid else _('Sin vigencia'),
            'reason': reason,
        }

    @api.model
    def _get_pos_payment_window_days(self):
        raw_value = self.env['ir.config_parameter'].sudo().get_param(
            'witann_group_subscriptions_pos.payment_window_days',
            str(self._DEFAULT_PAYMENT_WINDOW_DAYS),
        )
        try:
            days = int(raw_value)
        except (TypeError, ValueError):
            days = self._DEFAULT_PAYMENT_WINDOW_DAYS
        return max(0, days)

    def _get_recurring_lines(self):
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: line.product_id and line.product_id.product_tmpl_id.recurring_invoice
        )

    @api.model
    def _get_recurring_line_qty_for_pos(self, line):
        for field_name in ('product_uom_qty', 'quantity', 'qty'):
            if field_name in line._fields:
                return float(line[field_name] or 0.0)
        return 0.0

    @api.model
    def _extract_recurring_line_plan_pricing_for_pos(self, line):
        line = line and line[:1]
        if not line:
            return False, False

        plan_id = False
        pricing_id = False
        for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
            if field_name in line._fields and line[field_name]:
                plan_id = line[field_name].id
                break
        for field_name in ('subscription_pricing_id', 'pricing_id', 'recurring_pricing_id'):
            if field_name in line._fields and line[field_name]:
                pricing_id = line[field_name].id
                break
        return plan_id, pricing_id

    def _get_subscription_plan_name_for_pos(self, recurring_lines):
        self.ensure_one()

        if 'plan_id' in self._fields and self.plan_id:
            return self.plan_id.display_name

        names = []
        line_plan_fields = ('subscription_plan_id', 'plan_id', 'recurring_plan_id')
        for line in recurring_lines:
            for field_name in line_plan_fields:
                if field_name not in line._fields:
                    continue
                plan_value = line[field_name]
                if not plan_value:
                    continue
                if getattr(plan_value, 'display_name', False):
                    names.append(plan_value.display_name)
                    break

        names = sorted(set(name for name in names if name))
        return ', '.join(names) if names else False

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

    def _get_partner_field_value_for_pos(self, partner, field_candidates):
        partner.ensure_one()

        for field_name in field_candidates:
            field = partner._fields.get(field_name)
            if not field:
                continue
            value = partner[field_name]
            formatted = self._format_value_for_pos(value, field)
            if formatted:
                return formatted
        return False

    def _format_value_for_pos(self, value, field=False):
        if value in (False, None, ''):
            return False

        if field and field.type == 'selection':
            selection = field._description_selection(self.env) if callable(field.selection) else field.selection
            selection_map = dict(selection or [])
            return selection_map.get(value, value)

        if field and field.type == 'datetime':
            converted = fields.Datetime.to_datetime(value)
            if converted:
                return fields.Datetime.to_string(converted)
        if field and field.type == 'date':
            converted = fields.Date.to_date(value)
            if converted:
                return fields.Date.to_string(converted)

        if isinstance(value, datetime):
            return fields.Datetime.to_string(value)
        if isinstance(value, date):
            return fields.Date.to_string(value)
        return str(value)

    def _get_access_person_last_access_map_for_pos(self, partners):
        model_name = 'access_control.person'
        if model_name not in self.env.registry or not partners:
            return {}

        person_model = self.env[model_name].sudo()
        fields_map = person_model._fields
        if 'partner_id' not in fields_map:
            return {}

        candidate_fields = []
        for field_name in self._PARTNER_LAST_ACCESS_FIELD_CANDIDATES:
            field = fields_map.get(field_name)
            if field and field.type in ('date', 'datetime'):
                candidate_fields.append(field_name)

        for field_name, field in fields_map.items():
            if field.type not in ('date', 'datetime'):
                continue
            normalized_name = (field_name or '').lower()
            if any(
                token in normalized_name
                for token in ('last_access', 'last_entry', 'last_visit', 'ultimo_acceso', 'last_checkin')
            ):
                if field_name not in candidate_fields:
                    candidate_fields.append(field_name)

        if not candidate_fields:
            return {}

        records = person_model.search([('partner_id', 'in', partners.ids)], order='id desc')
        result = {}
        for record in records:
            partner_id = record.partner_id.id
            if not partner_id or partner_id in result:
                continue
            last_access_value = False
            for field_name in candidate_fields:
                if field_name not in record._fields:
                    continue
                field = record._fields[field_name]
                formatted = self._format_value_for_pos(record[field_name], field)
                if formatted:
                    last_access_value = formatted
                    break
            if last_access_value:
                result[partner_id] = last_access_value
        return result

    @api.model
    def _to_date(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return fields.Date.to_date(value)
