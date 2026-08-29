import logging
from datetime import datetime, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command, Domain

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    _WGS_SUBSCRIPTION_BUSINESS_TIMEZONE = 'America/Mexico_City'

    _WGS_ACCESS_ENABLED_STATE_TOKENS = (
        'progress',
        'in progress',
        'in_progress',
        'en progreso',
    )
    _WGS_ACCESS_SUSPENDED_STATE_TOKENS = (
        'pause',
        'paused',
        'pausa',
        'hold',
        'on hold',
        'suspend',
        'suspended',
    )
    _WGS_ACCESS_DISABLED_STATE_TOKENS = (
        'cancel',
        'cancelled',
        'canceled',
        'close',
        'closed',
        'churn',
        'churned',
        'draft',
        'upsell',
        'renew',
        'to renew',
        'por renovar',
    )
    _WGS_SUBSCRIPTION_PLAN_AUTO_CLOSE_DAY_FIELDS = (
        'auto_close_limit',
        'auto_close_days',
        'automatic_closing',
        'automatic_closing_days',
        'close_after_days',
        'close_days',
        'closing_days',
        'days_to_close',
        'renewal_grace_period',
        'grace_period_days',
    )
    _WGS_SUBSCRIPTION_NEXT_INVOICE_DATE_FIELDS = (
        'recurring_next_date',
        'next_invoice_date',
        'recurring_next_invoice_date',
    )
    _WGS_SUBSCRIPTION_START_DATE_FIELDS = (
        'wgs_effective_start_date',
        'start_date',
        'date_start',
        'subscription_start_date',
        'date_order',
    )
    _WGS_AUTO_CLOSE_CRON_BATCH_SIZE = 200
    _WGS_ACCESS_AUDIT_CRON_BATCH_SIZE = 200
    _WGS_DEFER_ACCESS_SYNC_CONTEXT_KEY = 'wgs_defer_access_sync'
    _WGS_ACCESS_AUDIT_ORDER_CURSOR_PARAM = 'witann_group_subscriptions.access_audit.order_cursor'
    _WGS_ACCESS_AUDIT_PERSON_CURSOR_PARAM = 'witann_group_subscriptions.access_audit.person_cursor'

    wgs_effective_start_date = fields.Date(
        string='Inicio de vigencia (WGS)',
        copy=True,
        help='Fecha efectiva de inicio de vigencia para operación en POS y control de acceso.',
    )
    participant_ids = fields.Many2many(
        'res.partner',
        'sale_order_subscription_participant_rel',
        'order_id',
        'partner_id',
        string='Participantes permitidos',
        copy=True,
        help='Listado total de participantes habilitados para esta suscripción, incluyendo titular.',
    )
    subscription_has_recurring_products = fields.Boolean(
        string='Tiene productos de suscripción',
        compute='_compute_subscription_participant_capacity',
    )
    subscription_max_participants_total = fields.Integer(
        string='Cupo total de participantes',
        compute='_compute_subscription_participant_capacity',
    )
    wgs_access_timezone_id = fields.Many2one(
        'access_control.timezone',
        string='Horario de acceso',
        domain="[('active', '=', True)]",
        help='Si se deja vacío, se usa el horario configurado en el paquete. '
             'Acceso general equivale a timezone_id=1.',
    )
    wgs_access_site_ids = fields.Many2many(
        'access_control.site',
        'sale_order_wgs_access_site_rel',
        'order_id',
        'site_id',
        string='Sitios de acceso WGS',
        copy=True,
        help='Snapshot de los sitios de acceso definidos al momento de vender o cambiar el paquete.',
    )
    wgs_access_timezone_snapshot_id = fields.Many2one(
        'access_control.timezone',
        string='Horario de acceso WGS (snapshot)',
        copy=True,
        help='Snapshot del horario de acceso definido al momento de vender o cambiar el paquete.',
    )
    wgs_domiciliation_contract_id = fields.Many2one(
        'wgs.subscription.domiciliation.contract',
        string='Contrato domiciliado WGS', copy=False, readonly=True,
    )

    @api.model
    def _wgs_get_subscription_business_timezone(self):
        """Return the authoritative timezone for subscription calendar dates."""
        return pytz.timezone(self._WGS_SUBSCRIPTION_BUSINESS_TIMEZONE)

    @api.model
    def _wgs_get_subscription_business_today(self, company=False, now=False):
        """Resolve the operational date without depending on user or server timezone."""
        # Keep company in the contract so callers make the business scope explicit.
        # All active subscription companies currently operate on the same calendar timezone.
        current_utc = now or fields.Datetime.now()
        if current_utc.tzinfo:
            current_utc = current_utc.astimezone(pytz.UTC)
        else:
            current_utc = pytz.UTC.localize(current_utc)
        return current_utc.astimezone(self._wgs_get_subscription_business_timezone()).date()

    @api.model
    def _wgs_get_subscription_business_date_from_datetime(self, value):
        """Convert UTC datetime fallbacks, such as date_order, to a business date."""
        if not isinstance(value, datetime):
            return fields.Date.to_date(value)
        if value.tzinfo:
            value = value.astimezone(pytz.UTC)
        else:
            value = pytz.UTC.localize(value)
        return value.astimezone(self._wgs_get_subscription_business_timezone()).date()

    @api.depends(
        'order_line',
        'order_line.product_id',
        'order_line.product_id.product_tmpl_id.recurring_invoice',
        'order_line.product_id.product_tmpl_id.max_participants_total',
    )
    def _compute_subscription_participant_capacity(self):
        for order in self:
            recurring_lines, max_capacity = order._get_subscription_capacity_data()
            order.subscription_has_recurring_products = bool(recurring_lines)
            order.subscription_max_participants_total = int(max_capacity)

    def _get_subscription_line_qty(self, line):
        for field_name in ('product_uom_qty', 'quantity', 'qty'):
            if field_name in line._fields:
                return float(line[field_name] or 0.0)
        return 0.0

    def _get_subscription_recurring_lines(self):
        self.ensure_one()
        recurring_lines = self.order_line.filtered(
            lambda line: (
                line.product_id
                and line.product_id.product_tmpl_id.recurring_invoice
                and not ('display_type' in line._fields and line.display_type)
                and self._get_subscription_line_qty(line) > 0
            )
        )
        return recurring_lines

    def _get_subscription_capacity_data(self):
        self.ensure_one()
        recurring_lines = self._get_subscription_recurring_lines()
        capacity = int(
            sum(
                self._get_subscription_line_qty(line) * line.product_id.product_tmpl_id.max_participants_total
                for line in recurring_lines
            )
        )
        return recurring_lines, capacity

    def _ensure_subscription_owner_is_participant(self):
        for order in self:
            recurring_lines, _max_capacity = order._get_subscription_capacity_data()
            if not recurring_lines or not order.partner_id:
                continue
            if order.partner_id in order.participant_ids:
                continue
            if order.id:
                order.with_context(skip_owner_participant_sync=True).write(
                    {'participant_ids': [Command.link(order.partner_id.id)]}
                )
            else:
                order.participant_ids = [Command.link(order.partner_id.id)]

    def copy_data(self, default=None):
        default = default or {}
        copied_data = super().copy_data(default=default)
        if 'participant_ids' in default:
            return copied_data

        for order, data in zip(self, copied_data):
            if order.participant_ids:
                data['participant_ids'] = [Command.set(order.participant_ids.ids)]
        return copied_data

    @api.onchange('partner_id', 'order_line', 'order_line.product_id')
    def _onchange_subscription_participants(self):
        self._ensure_subscription_owner_is_participant()

    @api.constrains('participant_ids', 'partner_id', 'order_line')
    def _check_subscription_participants(self):
        for order in self:
            recurring_lines, max_participants = order._get_subscription_capacity_data()
            if not recurring_lines:
                continue

            participants_count = len(order.participant_ids)
            if participants_count > max_participants:
                raise ValidationError(
                    _(
                        'No puedes asignar %(current)s participantes. El máximo permitido para esta suscripción es %(max)s.'
                    )
                    % {
                        'current': participants_count,
                        'max': max_participants,
                    }
                )

    def _wgs_get_access_related_partner_ids(self):
        partner_ids = set()
        for order in self:
            if order.partner_id:
                partner_ids.add(order.partner_id.id)
            partner_ids.update(order.participant_ids.ids)
        return partner_ids

    def _wgs_get_access_product_company_ids(self):
        self.ensure_one()
        company_ids = set()
        for line in self._get_subscription_recurring_lines():
            product = line.product_id
            if product and 'company_id' in product._fields and product.company_id:
                company_ids.add(product.company_id.id)
                continue
            product_tmpl = product.product_tmpl_id if product else False
            if product_tmpl and 'company_id' in product_tmpl._fields and product_tmpl.company_id:
                company_ids.add(product_tmpl.company_id.id)
                continue
        if not company_ids and 'company_id' in self._fields and self.company_id:
            company_ids.add(self.company_id.id)
        return sorted(company_ids)

    def _wgs_resolve_access_site_ids_from_config(self):
        self.ensure_one()
        explicit_site_ids = set()
        company_ids = set()
        for line in self._get_subscription_recurring_lines():
            product = line.product_id
            product_tmpl = product.product_tmpl_id if product else False
            if product_tmpl and 'wgs_access_site_ids' in product_tmpl._fields and product_tmpl.wgs_access_site_ids:
                explicit_site_ids.update(
                    product_tmpl.wgs_access_site_ids.filtered(lambda site: getattr(site, 'active', True)).ids
                )
                continue
            if product and 'company_id' in product._fields and product.company_id:
                company_ids.add(product.company_id.id)
                continue
            if product_tmpl and 'company_id' in product_tmpl._fields and product_tmpl.company_id:
                company_ids.add(product_tmpl.company_id.id)
                continue
        if explicit_site_ids:
            return sorted(explicit_site_ids)

        company_ids = sorted(company_ids) if company_ids else self._wgs_get_access_product_company_ids()
        if not company_ids:
            return []
        Site = self.env['access_control.site'].sudo()
        return Site.search(
            [('active', '=', True), ('company_id', 'in', company_ids)],
            order='id asc',
        ).ids

    def _wgs_resolve_access_timezone_from_config(self):
        self.ensure_one()
        if self.wgs_access_timezone_id:
            return self.wgs_access_timezone_id
        for line in self._get_subscription_recurring_lines():
            product_tmpl = line.product_id.product_tmpl_id if line.product_id else False
            if product_tmpl and product_tmpl.wgs_access_timezone_id:
                return product_tmpl.wgs_access_timezone_id
        return self.env.ref('access_control_api.access_timezone_general', raise_if_not_found=False)

    def _wgs_access_snapshot_signature(self):
        self.ensure_one()
        recurring_lines = self._get_subscription_recurring_lines()
        line_signature = tuple(
            sorted(
                (
                    line.product_id.id,
                    self._get_subscription_line_qty(line),
                )
                for line in recurring_lines
            )
        )
        return (
            line_signature,
            self.company_id.id if 'company_id' in self._fields and self.company_id else False,
            self.wgs_access_timezone_id.id if self.wgs_access_timezone_id else False,
        )

    def _wgs_update_access_snapshot(self, force=False):
        for order in self:
            if not order._get_subscription_recurring_lines():
                continue

            values = {}
            if force or not order.wgs_access_site_ids:
                values['wgs_access_site_ids'] = [Command.set(order._wgs_resolve_access_site_ids_from_config())]
            if force or not order.wgs_access_timezone_snapshot_id:
                timezone = order._wgs_resolve_access_timezone_from_config()
                values['wgs_access_timezone_snapshot_id'] = timezone.id if timezone else False

            if not values:
                continue
            super(SaleOrder, order.with_context(wgs_skip_access_snapshot_refresh=True)).write(values)
            order.invalidate_recordset(['wgs_access_site_ids', 'wgs_access_timezone_snapshot_id'])
            # Ensure invalid/archived site rows never leak into the physical sync source.
            if order.wgs_access_site_ids:
                active_sites = order.wgs_access_site_ids.filtered(lambda site: getattr(site, 'active', True))
                if len(active_sites) != len(order.wgs_access_site_ids):
                    super(SaleOrder, order.with_context(wgs_skip_access_snapshot_refresh=True)).write(
                        {'wgs_access_site_ids': [Command.set(active_sites.ids)]}
                    )
        return True

    def _wgs_get_access_site_ids(self):
        self.ensure_one()
        if self.wgs_access_site_ids:
            return self.wgs_access_site_ids.filtered(lambda site: getattr(site, 'active', True)).ids
        self._wgs_update_access_snapshot(force=False)
        return self.wgs_access_site_ids.filtered(lambda site: getattr(site, 'active', True)).ids

    def _wgs_get_access_timezone(self):
        self.ensure_one()
        if self.wgs_access_timezone_id:
            return self.wgs_access_timezone_id
        if self.wgs_access_timezone_snapshot_id:
            return self.wgs_access_timezone_snapshot_id
        self._wgs_update_access_snapshot(force=False)
        if self.wgs_access_timezone_snapshot_id:
            return self.wgs_access_timezone_snapshot_id
        return self.env.ref('access_control_api.access_timezone_general', raise_if_not_found=False)

    def _wgs_get_first_access_date_value(self, field_names):
        self.ensure_one()
        for field_name in field_names:
            if field_name not in self._fields:
                continue
            value = self[field_name]
            if value:
                return self._wgs_get_subscription_business_date_from_datetime(value)
        return False

    def _wgs_get_subscription_plan_from_line(self, line):
        line = line.exists() if line else self.env['sale.order.line']
        if not line:
            return False
        line.ensure_one()
        for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
            if field_name in line._fields and line[field_name]:
                return line[field_name]
        return False

    def _wgs_get_subscription_recurrence_delta(self, primary_recurring_line=False):
        self.ensure_one()
        primary_recurring_line = primary_recurring_line.exists() if primary_recurring_line else self.env['sale.order.line']
        plan = self._wgs_get_subscription_plan_from_line(primary_recurring_line)
        interval = 1
        unit = 'month'
        if plan and 'recurring_interval' in plan._fields and 'recurring_rule_type' in plan._fields:
            interval = plan.recurring_interval or 1
            unit = plan.recurring_rule_type or 'month'
        elif plan and 'billing_period_value' in plan._fields and 'billing_period_unit' in plan._fields:
            interval = plan.billing_period_value or 1
            unit = plan.billing_period_unit or 'month'
        elif plan and 'interval_number' in plan._fields and 'interval_type' in plan._fields:
            interval = plan.interval_number or 1
            unit = plan.interval_type or 'month'
        elif plan and 'duration' in plan._fields and 'duration_unit' in plan._fields:
            interval = plan.duration or 1
            unit = plan.duration_unit or 'month'
        elif primary_recurring_line and 'recurring_interval' in primary_recurring_line._fields:
            interval = primary_recurring_line.recurring_interval or 1
            unit = primary_recurring_line.recurring_rule_type or 'month'
        elif 'recurring_interval' in self._fields:
            interval = self.recurring_interval or 1
            unit = self.recurring_rule_type or 'month'

        interval = max(int(interval or 1), 1)
        unit_value = (unit or 'month').lower()
        if 'day' in unit_value:
            return relativedelta(days=interval)
        if 'week' in unit_value:
            return relativedelta(weeks=interval)
        if 'year' in unit_value:
            return relativedelta(years=interval)
        return relativedelta(months=interval)

    def _wgs_get_subscription_plan_auto_close_days(self, plan):
        plan = plan.exists() if plan else False
        if not plan:
            return 0

        for field_name in self._WGS_SUBSCRIPTION_PLAN_AUTO_CLOSE_DAY_FIELDS:
            field = plan._fields.get(field_name)
            if not field:
                continue
            try:
                value = plan[field_name]
            except Exception:
                continue
            if value in (False, None, ''):
                continue
            try:
                return max(int(value), 0)
            except (TypeError, ValueError):
                continue

        for field_name, field in plan._fields.items():
            if field.type not in ('integer', 'float'):
                continue
            normalized_name = (field_name or '').lower()
            normalized_label = (getattr(field, 'string', '') or '').lower()
            searchable = f'{normalized_name} {normalized_label}'
            if not any(token in searchable for token in ('close', 'closing', 'cerrar', 'cierre', 'grace', 'gracia')):
                continue
            if not any(token in searchable for token in ('day', 'days', 'dia', 'dias', 'días', 'limit')):
                continue
            try:
                return max(int(plan[field_name] or 0), 0)
            except (TypeError, ValueError):
                continue
        return 0

    def _wgs_get_subscription_auto_close_deadline(self, next_invoice_date=False, primary_recurring_line=False):
        due_date = fields.Date.to_date(next_invoice_date)
        if not due_date:
            return False

        plan = self._wgs_get_subscription_plan_from_line(primary_recurring_line)
        if not plan and 'plan_id' in self._fields and self.plan_id:
            plan = self.plan_id
        auto_close_days = self._wgs_get_subscription_plan_auto_close_days(plan)
        if auto_close_days <= 0:
            return False
        return due_date + timedelta(days=auto_close_days)

    def _wgs_normalize_next_invoice_date_for_access(self, next_invoice_date=False, hard_end_date=False):
        next_date = fields.Date.to_date(next_invoice_date)
        end_date = fields.Date.to_date(hard_end_date)
        if next_date and end_date and next_date == end_date:
            # Legacy imports and some manual corrections used the inclusive
            # period end as next_invoice_date. Access must remain valid through
            # that full day and expire on the following date.
            return end_date + timedelta(days=1)
        return next_date

    def _wgs_get_subscription_auto_close_deadline_from_order(self, today=False):
        self.ensure_one()
        recurring_lines = self._get_subscription_recurring_lines()
        if not recurring_lines:
            return False
        primary_recurring_line = recurring_lines.sorted(key=lambda line: line.id)[:1]
        start_date = self._wgs_get_first_access_date_value(
            self._WGS_SUBSCRIPTION_START_DATE_FIELDS
        )
        next_invoice_date = self._wgs_get_first_access_date_value(
            self._WGS_SUBSCRIPTION_NEXT_INVOICE_DATE_FIELDS
        )
        hard_end_date = self._wgs_get_first_access_date_value(
            ('date_end', 'end_date', 'subscription_end_date', 'recurring_end_date')
        )
        if start_date and (not next_invoice_date or next_invoice_date <= start_date):
            next_invoice_date = start_date + self._wgs_get_subscription_recurrence_delta(
                primary_recurring_line=primary_recurring_line
            )
        next_invoice_date = self._wgs_normalize_next_invoice_date_for_access(next_invoice_date, hard_end_date)
        return self._wgs_get_subscription_auto_close_deadline(
            next_invoice_date=next_invoice_date,
            primary_recurring_line=primary_recurring_line,
        )

    @api.model
    def _wgs_combine_or_domains(self, domains):
        """Return an ORM domain that ORs complete domain clauses."""
        domains = [Domain(domain) for domain in domains if domain is not None]
        if not domains:
            return None
        return Domain.OR(domains)

    @api.model
    def _wgs_get_resolved_date_candidate_domain(self, field_names, operator, value):
        """Build the SQL equivalent of _wgs_get_first_access_date_value()."""
        available_fields = [field_name for field_name in field_names if field_name in self._fields]
        if not available_fields:
            return None, None

        candidate_domains = []
        prior_fields_empty = Domain.TRUE
        for field_name in available_fields:
            candidate_domains.append(prior_fields_empty & Domain(field_name, operator, value))
            prior_fields_empty &= Domain(field_name, '=', False)
        return self._wgs_combine_or_domains(candidate_domains), prior_fields_empty

    @api.model
    def _wgs_get_subscription_auto_close_candidate_domain(self, today):
        """Select only orders that can possibly reach their close deadline today.

        The final deadline remains intentionally validated per order because the
        grace period belongs to the recurring plan and can differ by product.
        """
        domain = Domain([
            ('state', 'in', ['sale', 'done']),
            ('order_line.product_id.product_tmpl_id.recurring_invoice', '=', True),
        ])
        if 'is_subscription' in self._fields:
            domain &= Domain('is_subscription', '=', True)
        if 'subscription_state' in self._fields:
            domain &= Domain('subscription_state', '!=', False)
            terminal_state_values = self._wgs_get_subscription_terminal_state_values()
            if terminal_state_values:
                # Active domiciliation contracts own their operational state even
                # when the native recurring engine has already closed the order.
                domain &= Domain.OR([
                    Domain('wgs_domiciliation_contract_id.state', '=', 'active'),
                    Domain('subscription_state', 'not in', terminal_state_values),
                ])

        next_date_domain, missing_next_date_domain = self._wgs_get_resolved_date_candidate_domain(
            self._WGS_SUBSCRIPTION_NEXT_INVOICE_DATE_FIELDS,
            '<=',
            today,
        )
        start_date_domain, _unused_missing_start_date_domain = self._wgs_get_resolved_date_candidate_domain(
            self._WGS_SUBSCRIPTION_START_DATE_FIELDS,
            '<=',
            today,
        )
        date_domains = [domain for domain in [next_date_domain] if domain is not None]
        if missing_next_date_domain is not None and start_date_domain is not None:
            date_domains.append(missing_next_date_domain & start_date_domain)
        if date_domains:
            domain &= self._wgs_combine_or_domains(date_domains)
        return domain

    @api.model
    def _wgs_get_subscription_state_category_from_value(self, value):
        state_value = (value or '').strip().lower()
        if not state_value:
            return False
        if 'draft' in state_value:
            return 'draft'
        if 'upsell' in state_value:
            return 'upsell'
        if any(token in state_value for token in ('cancel', 'cancelled', 'canceled')):
            return 'cancel'
        if any(token in state_value for token in ('close', 'closed', 'churn', 'churned')):
            return 'closed'
        if any(token in state_value for token in ('renew', 'to renew', 'por renovar')):
            return 'renew'
        if any(token in state_value for token in self._WGS_ACCESS_SUSPENDED_STATE_TOKENS):
            return 'paused'
        if any(token in state_value for token in self._WGS_ACCESS_ENABLED_STATE_TOKENS):
            return 'progress'
        return 'other'

    @api.model
    def _wgs_get_subscription_terminal_state_values(self):
        field = self._fields.get('subscription_state')
        if not field or not getattr(field, 'selection', False):
            return []

        selection = field.selection
        if isinstance(selection, str):
            selection = getattr(self, selection, lambda: [])()
        if callable(selection):
            selection = selection(self.env[self._name])
        terminal_categories = {'cancel', 'closed', 'draft', 'upsell'}
        terminal_values = []
        for value, label in selection or []:
            categories = {
                self._wgs_get_subscription_state_category_from_value(value),
                self._wgs_get_subscription_state_category_from_value(label),
            }
            if terminal_categories.intersection(categories):
                terminal_values.append(value)
        return terminal_values

    def _wgs_get_subscription_state_category(self):
        self.ensure_one()
        if 'subscription_state' not in self._fields:
            return False
        return self._wgs_get_subscription_state_category_from_value(self.subscription_state)

    def _wgs_is_due_for_subscription_auto_close(self, today=False):
        self.ensure_one()
        contract = self.wgs_domiciliation_contract_id
        if contract and contract.state == 'active':
            business_today = fields.Date.to_date(today) or self._wgs_get_subscription_business_today(company=self.company_id)
            if business_today <= contract.term_end_date:
                return False
        if self._wgs_get_subscription_state_category() in ('cancel', 'closed', 'draft', 'upsell'):
            return False
        close_deadline = self._wgs_get_subscription_auto_close_deadline_from_order(today=today)
        today = fields.Date.to_date(today) or self._wgs_get_subscription_business_today(company=self.company_id)
        return bool(close_deadline and today >= close_deadline)

    def _wgs_find_subscription_closed_state_value(self):
        self.ensure_one()
        field = self._fields.get('subscription_state')
        if not field or not getattr(field, 'selection', False):
            return False

        selection = field.selection
        if isinstance(selection, str):
            selection = getattr(self, selection, lambda: [])()
        if callable(selection):
            selection = selection(self.env[self._name])
        normalized_selection = [(value, (label or '').lower()) for value, label in (selection or [])]
        for preferred_token in ('churn', 'closed', 'close', 'cancel'):
            for value, label in normalized_selection:
                value_text = str(value or '').lower()
                if preferred_token in value_text or preferred_token in label:
                    return value
        return False

    def _wgs_close_subscription_for_auto_close(self, today=False):
        self.ensure_one()
        if not self._wgs_is_due_for_subscription_auto_close(today=today):
            return False

        for method_name in ('action_close', 'action_subscription_close', 'set_close'):
            method = getattr(self, method_name, None)
            if not callable(method):
                continue
            try:
                method()
                if self._wgs_get_subscription_state_category() in ('cancel', 'closed'):
                    _logger.info('WGS ACCESS: subscription %s auto-closed with %s', self.name, method_name)
                    return True
                _logger.warning(
                    'WGS ACCESS: %s on subscription %s did not close it; falling back to subscription_state write',
                    method_name,
                    self.name,
                )
            except Exception as error:
                _logger.warning(
                    'WGS ACCESS: could not execute %s on auto-close subscription %s (%s)',
                    method_name,
                    self.name,
                    error,
                )

        closed_state = self._wgs_find_subscription_closed_state_value()
        if closed_state and 'subscription_state' in self._fields:
            self.write({'subscription_state': closed_state})
            _logger.info('WGS ACCESS: subscription %s auto-closed by subscription_state=%s', self.name, closed_state)
            return True
        return False

    def _wgs_is_confirmed_access_subscription_order(self):
        self.ensure_one()
        if 'state' in self._fields and self.state not in ('sale', 'done'):
            return False
        if 'is_subscription' in self._fields and not self.is_subscription:
            return False
        if 'subscription_state' in self._fields and not (self.subscription_state or '').strip():
            return False
        return bool(self._get_subscription_recurring_lines())

    def _wgs_classify_subscription_access_state(self):
        self.ensure_one()
        if not self._wgs_is_confirmed_access_subscription_order():
            return False
        if 'subscription_state' not in self._fields:
            return False

        # A domiciliation contract owns entitlement for its entire forced term.
        # Native recurring jobs can mark the source order closed after a missed
        # invoice; that is an accounting state, not a cancellation of the WGS
        # contract and must not prevent its overdue installments from being paid.
        contract = self.wgs_domiciliation_contract_id
        if contract:
            return contract.wgs_get_operational_status().get('access_state') or False

        state_value = (self.subscription_state or '').strip().lower()
        if not state_value:
            return False
        if any(token in state_value for token in self._WGS_ACCESS_SUSPENDED_STATE_TOKENS):
            return 'suspended'
        if any(token in state_value for token in self._WGS_ACCESS_DISABLED_STATE_TOKENS):
            return False
        if not any(token in state_value for token in self._WGS_ACCESS_ENABLED_STATE_TOKENS):
            return False

        today = self._wgs_get_subscription_business_today(company=self.company_id)
        start_date = self._wgs_get_first_access_date_value(
            ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date', 'date_order')
        )
        if start_date and start_date > today:
            return False

        next_invoice_date = self._wgs_get_first_access_date_value(
            ('recurring_next_date', 'next_invoice_date', 'recurring_next_invoice_date')
        )
        hard_end_date = self._wgs_get_first_access_date_value(
            ('date_end', 'end_date', 'subscription_end_date', 'recurring_end_date')
        )
        next_invoice_date = self._wgs_normalize_next_invoice_date_for_access(next_invoice_date, hard_end_date)
        if next_invoice_date and next_invoice_date <= today:
            return False

        if hard_end_date and hard_end_date < today:
            return False

        return 'enabled'

    @api.model
    def _wgs_get_related_subscription_orders_for_partner(self, partner):
        if not partner:
            return self.browse()
        domain = [
            ('state', 'in', ['sale', 'done']),
            '|',
            ('partner_id', '=', partner.id),
            ('participant_ids', 'in', partner.id),
        ]
        if 'order_line' in self._fields:
            domain.append(('order_line.product_id.product_tmpl_id.recurring_invoice', '=', True))
        orders = self.sudo().search(domain, order='id asc')
        return orders.filtered(lambda order: order._wgs_is_confirmed_access_subscription_order())

    @api.model
    def _wgs_get_access_profile_for_partner(self, partner):
        profile = {
            'access_state': False,
            'site_ids': [],
            'order_ids': [],
            'blocked': False,
            'block_reason': False,
        }
        orders = self._wgs_get_related_subscription_orders_for_partner(partner)
        if not orders:
            if getattr(partner, 'wgs_access_blocked', False):
                profile['blocked'] = True
                profile['block_reason'] = partner.wgs_access_block_reason or False
            return profile

        enabled = False
        suspended = False
        enabled_site_ids = set()
        enabled_timezones = self.env['access_control.timezone'].sudo()
        considered_orders = []
        for order in orders:
            state = order._wgs_classify_subscription_access_state()
            if not state:
                continue
            considered_orders.append(order.id)
            if state == 'enabled':
                enabled = True
                enabled_site_ids.update(order._wgs_get_access_site_ids())
                order_timezone = order._wgs_get_access_timezone()
                if order_timezone:
                    enabled_timezones |= order_timezone
            elif state == 'suspended':
                suspended = True

        profile['order_ids'] = considered_orders
        if enabled:
            general_timezone = enabled_timezones.filtered(lambda timezone: int(timezone.timezone_id or 0) == 1)[:1]
            access_timezone = general_timezone or enabled_timezones.sorted(key=lambda timezone: int(timezone.timezone_id or 0))[:1]
            profile['site_ids'] = sorted(enabled_site_ids)
            profile['access_timezone_id'] = access_timezone.id if access_timezone else False
            profile['access_state'] = 'enabled'
        elif suspended:
            profile['access_state'] = 'suspended'
        if getattr(partner, 'wgs_access_blocked', False):
            profile['blocked'] = True
            profile['block_reason'] = partner.wgs_access_block_reason or False
            profile['access_state'] = 'suspended'
        return profile

    @api.model
    def _wgs_sync_access_control_partner(self, partner):
        if not partner:
            return False

        profile = self._wgs_get_access_profile_for_partner(partner)
        Person = self.env['access_control.person'].sudo()
        person = Person.search([('partner_id', '=', partner.id)], limit=1)
        access_state = profile['access_state']
        site_ids = profile['site_ids']

        if profile.get('blocked'):
            if person:
                vals = {
                    'managed_by_subscription': True,
                    'access_state': 'suspended',
                }
                if person.active:
                    vals['active'] = False
                if person.active or person.access_state != 'suspended' or not person.managed_by_subscription:
                    person.write(vals)
            _logger.info(
                'WGS ACCESS: person blocked partner=%s person=%s reason=%s orders=%s',
                partner.id,
                person.id if person else False,
                profile.get('block_reason') or '',
                profile['order_ids'],
            )
            return person

        if access_state == 'enabled' and not site_ids:
            _logger.warning(
                'WGS ACCESS: no se encontraron sitios para partner=%s order_ids=%s; acceso desactivado por seguridad',
                partner.id,
                profile['order_ids'],
            )
            if person:
                vals = {
                    'managed_by_subscription': True,
                    'access_state': 'suspended',
                }
                if person.active:
                    vals['active'] = False
                person.write(vals)
            return False

        if access_state == 'enabled':
            vals = {
                'partner_id': partner.id,
                'active': True,
                'access_state': access_state,
                'site_ids': [Command.set(site_ids)],
                'managed_by_subscription': True,
                'access_timezone_id': profile.get('access_timezone_id') or False,
            }
            if person:
                if not person.global_user_id:
                    person.action_assign_global_user_id()
                current_site_ids = set(person.site_ids.ids)
                desired_site_ids = set(site_ids)
                if (
                    not person.active
                    or person.access_state != access_state
                    or current_site_ids != desired_site_ids
                    or person.access_timezone_id.id != (profile.get('access_timezone_id') or False)
                    or not person.managed_by_subscription
                ):
                    person.write(vals)
            else:
                person = Person.create(vals)
            _logger.info(
                'WGS ACCESS: person upserted partner=%s person=%s state=%s sites=%s orders=%s',
                partner.id,
                person.id,
                access_state,
                site_ids,
                profile['order_ids'],
            )
            return person

        if person and person.managed_by_subscription:
            vals = {
                'managed_by_subscription': True,
                'access_state': 'suspended',
            }
            if person.active:
                vals['active'] = False
            if person.active or person.access_state != 'suspended' or not person.managed_by_subscription:
                person.write(vals)
                _logger.info(
                    'WGS ACCESS: person deactivated partner=%s person=%s orders=%s',
                    partner.id,
                    person.id,
                    profile['order_ids'],
                )
        return person

    def _wgs_sync_access_control_people(self, extra_partner_ids=None):
        partner_ids = set(extra_partner_ids or [])
        partner_ids.update(self._wgs_get_access_related_partner_ids())
        if not partner_ids:
            return
        partners = self.env['res.partner'].sudo().browse(sorted(partner_ids)).exists()
        for partner in partners:
            self._wgs_sync_access_control_partner(partner)

    def _wgs_sync_access_control_people_if_not_deferred(self, extra_partner_ids=None):
        if self.env.context.get(self._WGS_DEFER_ACCESS_SYNC_CONTEXT_KEY):
            return
        self._wgs_sync_access_control_people(extra_partner_ids=extra_partner_ids)

    @api.model
    def _wgs_search_rotating_id_page(self, model, domain, after_id=0, limit=200):
        """Read one bounded page and wrap to the first page after a full pass."""
        limit = max(1, int(limit or 1))
        after_id = max(0, int(after_id or 0))
        records = model.search(domain + [('id', '>', after_id)], order='id asc', limit=limit)
        if not records and after_id:
            records = model.search(domain, order='id asc', limit=limit)
        next_cursor = records[-1:].id if records else 0
        return records, next_cursor

    @api.model
    def _wgs_get_access_audit_cron_cursors(self):
        ICP = self.env['ir.config_parameter'].sudo()

        def _get_cursor(key):
            try:
                return max(0, int(ICP.get_param(key, '0') or 0))
            except (TypeError, ValueError):
                return 0

        return {
            'order_after_id': _get_cursor(self._WGS_ACCESS_AUDIT_ORDER_CURSOR_PARAM),
            'person_after_id': _get_cursor(self._WGS_ACCESS_AUDIT_PERSON_CURSOR_PARAM),
        }

    @api.model
    def _wgs_set_access_audit_cron_cursors(self, order_after_id=0, person_after_id=0):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(
            self._WGS_ACCESS_AUDIT_ORDER_CURSOR_PARAM,
            str(max(0, int(order_after_id or 0))),
        )
        ICP.set_param(
            self._WGS_ACCESS_AUDIT_PERSON_CURSOR_PARAM,
            str(max(0, int(person_after_id or 0))),
        )

    @api.model
    def _wgs_get_subscription_access_audit_partner_ids(
        self,
        batch_limit=5000,
        order_after_id=0,
        person_after_id=0,
    ):
        domain = [('state', 'in', ['sale', 'done'])]
        if 'order_line' in self._fields:
            domain.append(('order_line.product_id.product_tmpl_id.recurring_invoice', '=', True))
        orders, next_order_after_id = self._wgs_search_rotating_id_page(
            self.sudo(),
            domain,
            after_id=order_after_id,
            limit=batch_limit,
        )
        orders = orders.filtered(lambda order: order._get_subscription_recurring_lines())
        partner_ids = set()
        for order in orders:
            partner_ids.update(order._wgs_get_access_related_partner_ids())

        Person = self.env['access_control.person'].sudo()
        managed_people, next_person_after_id = self._wgs_search_rotating_id_page(Person, [
            ('managed_by_subscription', '=', True),
            ('partner_id', '!=', False),
            '|',
            ('active', '=', True),
            ('access_state', '=', 'enabled'),
        ], after_id=person_after_id, limit=batch_limit)
        partner_ids.update(managed_people.mapped('partner_id').ids)
        return {
            'partner_ids': sorted(partner_ids),
            'order_count': len(orders),
            'next_order_after_id': next_order_after_id,
            'next_person_after_id': next_person_after_id,
        }

    @api.model
    def _wgs_build_subscription_access_audit_line(self, partner):
        profile = self._wgs_get_access_profile_for_partner(partner)
        Person = self.env['access_control.person'].sudo()
        person = Person.search([('partner_id', '=', partner.id)], limit=1)
        expected_state = profile.get('access_state') or False
        expected_site_ids = set(profile.get('site_ids') or [])
        expected_timezone_id = profile.get('access_timezone_id') or False
        expected_active = expected_state == 'enabled' and bool(expected_site_ids)

        if expected_active:
            if not person:
                return {
                    'issue': 'missing_person',
                    'partner_id': partner.id,
                    'person_id': False,
                    'expected_active': True,
                    'expected_state': expected_state,
                    'expected_site_ids': sorted(expected_site_ids),
                    'expected_timezone_id': expected_timezone_id,
                    'current_active': False,
                    'current_state': False,
                    'current_site_ids': [],
                    'current_timezone_id': False,
                    'order_ids': profile.get('order_ids') or [],
                }
            current_site_ids = set(person.site_ids.ids)
            current_timezone_id = person.access_timezone_id.id if person.access_timezone_id else False
            if (
                not person.active
                or person.access_state != 'enabled'
                or current_site_ids != expected_site_ids
                or current_timezone_id != expected_timezone_id
                or not person.managed_by_subscription
            ):
                return {
                    'issue': 'person_mismatch',
                    'partner_id': partner.id,
                    'person_id': person.id,
                    'expected_active': True,
                    'expected_state': expected_state,
                    'expected_site_ids': sorted(expected_site_ids),
                    'expected_timezone_id': expected_timezone_id,
                    'current_active': bool(person.active),
                    'current_state': person.access_state or False,
                    'current_site_ids': sorted(current_site_ids),
                    'current_timezone_id': current_timezone_id,
                    'current_managed_by_subscription': bool(person.managed_by_subscription),
                    'order_ids': profile.get('order_ids') or [],
                }
            return False

        if person and person.managed_by_subscription and (person.active or person.access_state == 'enabled'):
            return {
                'issue': 'stale_managed_access',
                'partner_id': partner.id,
                'person_id': person.id,
                'expected_active': False,
                'expected_state': expected_state,
                'expected_site_ids': sorted(expected_site_ids),
                'expected_timezone_id': expected_timezone_id,
                'current_active': bool(person.active),
                'current_state': person.access_state or False,
                'current_site_ids': sorted(person.site_ids.ids),
                'current_timezone_id': person.access_timezone_id.id if person.access_timezone_id else False,
                'current_managed_by_subscription': True,
                'order_ids': profile.get('order_ids') or [],
            }
        return False

    @api.model
    def wgs_audit_subscription_access_control(
        self,
        repair=False,
        batch_limit=5000,
        partner_ids=None,
        order_after_id=0,
        person_after_id=0,
    ):
        if partner_ids is None:
            audit_source = self._wgs_get_subscription_access_audit_partner_ids(
                batch_limit=batch_limit,
                order_after_id=order_after_id,
                person_after_id=person_after_id,
            )
            partner_ids = audit_source['partner_ids']
            order_count = audit_source['order_count']
        else:
            partner_ids = sorted({int(partner_id) for partner_id in partner_ids if partner_id})
            order_count = 0
            audit_source = {
                'next_order_after_id': order_after_id,
                'next_person_after_id': person_after_id,
            }
        partners = self.env['res.partner'].sudo().browse(partner_ids).exists()
        lines = []
        repaired_partner_ids = []

        for partner in partners:
            line = self._wgs_build_subscription_access_audit_line(partner)
            if not line:
                continue
            lines.append(line)
            if repair:
                self._wgs_sync_access_control_partner(partner)
                repaired_partner_ids.append(partner.id)

        issue_counts = {}
        for line in lines:
            issue = line.get('issue') or 'unknown'
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

        summary = {
            'checked_partners': len(partners),
            'checked_orders': order_count,
            'issues': len(lines),
            'issue_counts': issue_counts,
            'repaired': len(repaired_partner_ids),
            'repaired_partner_ids': repaired_partner_ids,
            'lines': lines,
            'next_order_after_id': audit_source['next_order_after_id'],
            'next_person_after_id': audit_source['next_person_after_id'],
        }
        _logger.info(
            'WGS ACCESS: audit repair=%s checked_partners=%s checked_orders=%s issues=%s issue_counts=%s repaired=%s',
            bool(repair),
            summary['checked_partners'],
            summary['checked_orders'],
            summary['issues'],
            summary['issue_counts'],
            summary['repaired'],
        )
        return summary

    @api.model
    def _cron_wgs_close_overdue_subscriptions(self, limit=None):
        today = self._wgs_get_subscription_business_today()
        search_limit = max(1, int(limit or self._WGS_AUTO_CLOSE_CRON_BATCH_SIZE))
        subscriptions = self.sudo().search(
            self._wgs_get_subscription_auto_close_candidate_domain(today),
            order='id asc',
            limit=search_limit,
        )

        closed = self.browse()
        for subscription in subscriptions:
            deferred_subscription = subscription.with_context(
                **{self._WGS_DEFER_ACCESS_SYNC_CONTEXT_KEY: True}
            )
            if deferred_subscription._wgs_close_subscription_for_auto_close(today=today):
                closed |= subscription

        if closed:
            closed.with_context(access_sync_priority=True)._wgs_sync_access_control_people()
            _logger.info(
                'WGS ACCESS: auto-closed %s overdue subscriptions by plan grace period (candidates=%s, limit=%s)',
                len(closed),
                len(subscriptions),
                search_limit,
            )
        return len(closed)

    @api.model
    def _cron_wgs_sync_subscription_access_control(self, batch_limit=None):
        cursors = self._wgs_get_access_audit_cron_cursors()
        repair_summary = self.wgs_audit_subscription_access_control(
            repair=True,
            batch_limit=max(1, int(batch_limit or self._WGS_ACCESS_AUDIT_CRON_BATCH_SIZE)),
            **cursors,
        )
        self._wgs_set_access_audit_cron_cursors(
            order_after_id=repair_summary['next_order_after_id'],
            person_after_id=repair_summary['next_person_after_id'],
        )
        verification_summary = self.wgs_audit_subscription_access_control(
            repair=False,
            partner_ids=repair_summary['repaired_partner_ids'],
        )
        _logger.info(
            'WGS ACCESS: post-sync verification checked_partners=%s remaining_issues=%s issue_counts=%s',
            verification_summary.get('checked_partners'),
            verification_summary.get('issues'),
            verification_summary.get('issue_counts'),
        )
        repair_summary['post_sync_issues'] = verification_summary.get('issues', 0)
        repair_summary['post_sync_issue_counts'] = verification_summary.get('issue_counts', {})
        return repair_summary

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._ensure_subscription_owner_is_participant()
        orders._wgs_update_access_snapshot(force=True)
        orders._wgs_sync_access_control_people()
        return orders

    def write(self, vals):
        before_partner_ids = self._wgs_get_access_related_partner_ids()
        before_snapshot_signatures = {
            order.id: order._wgs_access_snapshot_signature()
            for order in self
            if order.id
        }
        res = super().write(vals)
        if not self.env.context.get('skip_owner_participant_sync'):
            self._ensure_subscription_owner_is_participant()
        if not self.env.context.get('wgs_skip_access_snapshot_refresh'):
            changed_orders = self.browse()
            for order in self:
                if not order.id:
                    continue
                if before_snapshot_signatures.get(order.id) != order._wgs_access_snapshot_signature():
                    changed_orders |= order
            if changed_orders:
                changed_orders._wgs_update_access_snapshot(force=True)
            else:
                self._wgs_update_access_snapshot(force=False)
        sync_orders = self.with_context(access_sync_priority=True) if 'wgs_access_timezone_id' in vals else self
        sync_orders._wgs_sync_access_control_people_if_not_deferred(extra_partner_ids=before_partner_ids)
        return res

    def unlink(self):
        impacted_partner_ids = self._wgs_get_access_related_partner_ids()
        res = super().unlink()
        if impacted_partner_ids:
            self._wgs_sync_access_control_people_if_not_deferred(extra_partner_ids=impacted_partner_ids)
        return res

    def action_confirm(self):
        res = super().action_confirm()
        self._wgs_sync_access_control_people_if_not_deferred()
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._wgs_sync_access_control_people_if_not_deferred()
        return res

    def action_close(self):
        super_method = getattr(super(), 'action_close', None)
        if not super_method:
            return False
        res = super_method()
        self._wgs_sync_access_control_people_if_not_deferred()
        return res

    def action_subscription_close(self):
        super_method = getattr(super(), 'action_subscription_close', None)
        if not super_method:
            return False
        res = super_method()
        self._wgs_sync_access_control_people_if_not_deferred()
        return res


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    _WGS_ACCESS_LINE_REFRESH_FIELDS = {
        'product_id',
        'product_uom_qty',
        'quantity',
        'qty',
        'display_type',
    }

    def _wgs_access_impacted_orders(self):
        return self.mapped('order_id').filtered(
            lambda order: hasattr(order, '_wgs_update_access_snapshot')
            and hasattr(order, '_wgs_sync_access_control_people')
        )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        orders = lines._wgs_access_impacted_orders()
        if orders:
            orders._wgs_update_access_snapshot(force=True)
            orders._wgs_sync_access_control_people()
        return lines

    def write(self, vals):
        should_refresh = bool(self._WGS_ACCESS_LINE_REFRESH_FIELDS.intersection(vals))
        before_orders = self._wgs_access_impacted_orders() if should_refresh else self.env['sale.order']
        before_partner_ids = set()
        for order in before_orders:
            before_partner_ids.update(order._wgs_get_access_related_partner_ids())

        res = super().write(vals)

        if should_refresh:
            orders = (before_orders | self._wgs_access_impacted_orders()).exists()
            if orders:
                orders._wgs_update_access_snapshot(force=True)
                orders._wgs_sync_access_control_people(extra_partner_ids=before_partner_ids)
        return res

    def unlink(self):
        orders = self._wgs_access_impacted_orders()
        before_partner_ids = set()
        for order in orders:
            before_partner_ids.update(order._wgs_get_access_related_partner_ids())

        res = super().unlink()

        orders = orders.exists()
        if orders:
            orders._wgs_update_access_snapshot(force=True)
            orders._wgs_sync_access_control_people(extra_partner_ids=before_partner_ids)
        return res
