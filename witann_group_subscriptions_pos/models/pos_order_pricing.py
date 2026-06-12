import logging
from datetime import timedelta, date, datetime

from dateutil.relativedelta import relativedelta

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PosOrderPricingMixin(models.Model):
    _inherit = 'pos.order'
    _WGS_PLAN_FIELD_NAMES = ('subscription_plan_id', 'plan_id', 'recurring_plan_id')
    _WGS_PRICING_FIELD_NAMES = ('subscription_pricing_id', 'pricing_id', 'recurring_pricing_id')
    _WGS_PERIOD_ALIGNMENT_FIELD_NAMES = (
        'align_to_period_start',
        'align_to_period',
        'align_billing_period',
        'align_invoice_period',
        'align_invoice_dates',
        'auto_align_to_period_start',
        'is_aligned_to_period_start',
        'invoice_on_period_start',
    )
    _WGS_PRODUCT_PRICING_RELATION_FIELD_NAMES = (
        'subscription_pricing_ids',
        'recurring_pricing_ids',
        'subscription_pricing_id',
        'recurring_pricing_id',
    )
    _WGS_SUBSCRIPTION_PRICING_PRODUCT_FIELD_NAMES = ('product_id', 'product_variant_id')
    _WGS_SUBSCRIPTION_PRICING_TEMPLATE_FIELD_NAMES = ('product_tmpl_id', 'product_template_id')
    _WGS_PRICELIST_ITEM_PRODUCT_FIELD_NAMES = ('product_id', 'product_variant_id')
    _WGS_PRICELIST_ITEM_TEMPLATE_FIELD_NAMES = ('product_tmpl_id', 'product_template_id')

    def _wgs_get_env_cache(self, attribute_name):
        cache = getattr(self.env, attribute_name, None)
        if cache is None:
            cache = {}
            setattr(self.env, attribute_name, cache)
        return cache

    def _wgs_get_relation_field_names(
        self,
        model_name,
        comodel_name,
        *,
        relation_types=('many2one',),
        preferred_field_names=(),
    ):
        if model_name not in self.env.registry:
            return ()

        cache = self._wgs_get_env_cache('_wgs_relation_field_names_cache')
        cache_key = (
            model_name,
            comodel_name,
            tuple(relation_types or ()),
            tuple(preferred_field_names or ()),
        )
        if cache_key in cache:
            return cache[cache_key]

        model = self.env[model_name]
        supported = []
        seen = set()
        for field_name in preferred_field_names:
            field = model._fields.get(field_name)
            if not field:
                continue
            if field.type not in relation_types:
                continue
            if getattr(field, 'comodel_name', False) != comodel_name:
                continue
            supported.append(field_name)
            seen.add(field_name)
        result = tuple(supported)
        cache[cache_key] = result
        return result

    def _wgs_get_upsale_source_recurring_amount(self, source_order, tax_included=False):
        source_order.ensure_one()
        recurring_total = self._wgs_get_order_recurring_total_amount(
            source_order,
            include_taxes=tax_included,
        )
        return round(max(float(recurring_total or 0.0), 0.0), 2)

    def _wgs_get_order_recurring_total_amount(self, sale_order, include_taxes=False):
        sale_order.ensure_one()
        recurring_lines = sale_order.order_line.filtered(
            lambda so_line: self._wgs_is_recurring_so_line(so_line) and abs(self._wgs_get_so_line_qty(so_line)) > 0
        )
        total = 0.0
        for so_line in recurring_lines:
            qty = abs(self._wgs_get_so_line_qty(so_line))
            if include_taxes:
                total += self._wgs_get_sale_order_line_total_with_tax(so_line, qty_override=qty)
            else:
                discount = float(so_line.discount or 0.0) if 'discount' in so_line._fields else 0.0
                total += qty * float(so_line.price_unit or 0.0) * (1 - (discount / 100.0))
        return max(total, 0.0)

    def _wgs_get_sale_order_line_total_with_tax(self, so_line, qty_override=False):
        so_line.ensure_one()
        qty = abs(float(qty_override if qty_override is not False else self._wgs_get_so_line_qty(so_line)))
        discount = float(so_line.discount or 0.0) if 'discount' in so_line._fields else 0.0
        unit_price = float(so_line.price_unit or 0.0) * (1 - (discount / 100.0))
        taxes = self.env['account.tax']
        for field_name in ('tax_id', 'tax_ids'):
            if field_name in so_line._fields and so_line[field_name]:
                taxes = so_line[field_name]
                break
        if not taxes and so_line.product_id:
            taxes = so_line.product_id.taxes_id
        if not taxes and so_line.product_id and 'taxes_id' in so_line.product_id.product_tmpl_id._fields:
            taxes = so_line.product_id.product_tmpl_id.taxes_id
        if not taxes:
            return round(max(unit_price * qty, 0.0), 2)
        currency = so_line.order_id.currency_id if 'currency_id' in so_line.order_id._fields else False
        partner = so_line.order_id.partner_id if 'partner_id' in so_line.order_id._fields else False
        fiscal_position = so_line.order_id.fiscal_position_id if 'fiscal_position_id' in so_line.order_id._fields else False
        if fiscal_position and hasattr(fiscal_position, 'map_tax'):
            taxes = fiscal_position.map_tax(taxes, product=so_line.product_id, partner=partner or False)
        result = taxes.compute_all(unit_price, currency=currency, quantity=qty, product=so_line.product_id, partner=partner)
        return round(max(float(result.get('total_included') or 0.0), 0.0), 2)

    def _wgs_get_price_with_taxes_for_pos(self, product, base_price, partner=False, company=False, fiscal_position=False):
        product.ensure_one()
        base_price = float(base_price or 0.0)
        taxes = product.taxes_id
        if not taxes and 'taxes_id' in product.product_tmpl_id._fields:
            taxes = product.product_tmpl_id.taxes_id
        if not taxes:
            return round(max(base_price, 0.0), 2)

        requested_company = (
            company
            or getattr(product, 'company_id', False)
            or getattr(product.product_tmpl_id, 'company_id', False)
            or self.company_id
            or self.env.company
        )
        if requested_company:
            filtered_taxes = taxes.filtered(lambda tax: not tax.company_id or tax.company_id == requested_company)
            if filtered_taxes:
                taxes = filtered_taxes

        if fiscal_position and hasattr(fiscal_position, 'map_tax'):
            taxes = fiscal_position.map_tax(taxes, product=product, partner=partner or False)

        currency_company = requested_company
        tax_companies = taxes.mapped('company_id').filtered(bool)
        if len(tax_companies) == 1:
            currency_company = tax_companies[0]
        currency = currency_company.currency_id if currency_company and getattr(currency_company, 'currency_id', False) else False
        result = taxes.compute_all(base_price, currency=currency, quantity=1.0, product=product, partner=partner or False)
        return round(max(float(result.get('total_included') or 0.0), 0.0), 2)

    def _wgs_is_recurring_so_line(self, so_line):
        so_line.ensure_one()
        if 'display_type' in so_line._fields and so_line.display_type:
            return False
        if so_line.product_id and so_line.product_id.product_tmpl_id.recurring_invoice:
            return True

        for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
            if field_name in so_line._fields and so_line[field_name]:
                return True
        for field_name in ('subscription_pricing_id', 'pricing_id', 'recurring_pricing_id'):
            if field_name in so_line._fields and so_line[field_name]:
                return True
        return False

    def _wgs_get_so_line_qty(self, so_line):
        for field_name in ('product_uom_qty', 'quantity', 'qty'):
            if field_name in so_line._fields:
                return float(so_line[field_name] or 0.0)
        return 0.0

    def _wgs_get_current_subscription_period_bounds(self, source_order, today=False, preferred_line=False):
        source_order.ensure_one()
        today = fields.Date.to_date(today) or fields.Date.context_today(self)

        period_end = self._wgs_get_first_date_from_order(source_order, ('recurring_next_date', 'next_invoice_date'))
        delta = self._wgs_get_order_recurrence_delta(source_order, preferred_line=preferred_line)
        if not period_end:
            start_date = self._wgs_get_first_date_from_order(
                source_order,
                ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date', 'date_order'),
            ) or today
            period_start = start_date
            period_end = period_start + delta
            safety_counter = 0
            while period_end <= today and safety_counter < 120:
                period_start = period_end
                period_end = period_start + delta
                safety_counter += 1
        else:
            period_start = period_end - delta

        if isinstance(period_start, datetime):
            period_start = period_start.date()
        if isinstance(period_end, datetime):
            period_end = period_end.date()

        if isinstance(period_start, date) and isinstance(period_end, date):
            return period_start, period_end
        return False, False

    def _wgs_get_order_recurrence_delta(self, sale_order, preferred_line=False):
        sale_order.ensure_one()

        interval = 1
        unit = 'month'
        plan = self._wgs_extract_plan_record_from_subscription_line(preferred_line)
        if not plan:
            plan = self._wgs_extract_plan_record_from_sale_order(sale_order)
        if plan:
            interval, unit = self._wgs_extract_interval_from_plan(plan)
        elif {'recurring_interval', 'recurring_rule_type'}.issubset(sale_order._fields):
            interval = int(sale_order.recurring_interval or 1)
            unit = sale_order.recurring_rule_type or 'month'

        interval = max(1, int(interval or 1))
        unit_value = (unit or 'month').lower()
        if 'day' in unit_value:
            return relativedelta(days=interval)
        if 'week' in unit_value:
            return relativedelta(weeks=interval)
        if 'year' in unit_value:
            return relativedelta(years=interval)
        return relativedelta(months=interval)

    def _wgs_extract_plan_record_from_subscription_line(self, so_line):
        so_line = so_line.exists() if so_line else self.env['sale.order.line']
        if not so_line:
            return False
        so_line.ensure_one()
        for field_name in self._WGS_PLAN_FIELD_NAMES:
            if field_name in so_line._fields and so_line[field_name]:
                return so_line[field_name]
        return False

    def _wgs_extract_plan_record_from_sale_order(self, sale_order):
        sale_order.ensure_one()

        recurring_lines = sale_order.order_line.filtered(
            lambda so_line: self._wgs_is_recurring_so_line(so_line)
        )
        line_plan_fields = ('subscription_plan_id', 'plan_id', 'recurring_plan_id')
        for so_line in recurring_lines:
            for field_name in line_plan_fields:
                if field_name in so_line._fields and so_line[field_name]:
                    return so_line[field_name]
        if 'plan_id' in sale_order._fields and sale_order.plan_id:
            return sale_order.plan_id
        return False

    def _wgs_get_first_date_from_order(self, sale_order, field_names):
        sale_order.ensure_one()
        for field_name in field_names:
            if field_name not in sale_order._fields:
                continue
            value = sale_order[field_name]
            converted = self._wgs_to_date(value)
            if converted:
                return converted
        return False

    def _wgs_to_date(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return fields.Date.to_date(value)

    def _wgs_resolve_plan_record(self, product, plan_id=False, pricing_id=False):
        product.ensure_one()
        resolved_plan = False
        if pricing_id and 'sale.subscription.pricing' in self.env.registry:
            pricing = self.env['sale.subscription.pricing'].browse(int(pricing_id)).exists()
            if pricing:
                resolved_plan = self._wgs_extract_plan_record_from_pricing(pricing)
        if not resolved_plan and plan_id:
            resolved_plan = self._wgs_find_plan_record_by_id(int(plan_id))
        if not resolved_plan:
            resolved_plan = self._wgs_extract_plan_record_from_product(product)
        return resolved_plan

    def _wgs_find_plan_record_by_id(self, plan_id):
        if not plan_id:
            return False
        candidate_model_names = set()

        for model_name in ('sale.order', 'sale.order.line', 'product.product', 'product.template'):
            if model_name not in self.env.registry:
                continue
            for field in self.env[model_name]._fields.values():
                if field.type != 'many2one':
                    continue
                comodel_name = getattr(field, 'comodel_name', '')
                if self._wgs_is_plan_model_name(comodel_name):
                    candidate_model_names.add(comodel_name)

        for model_name in sorted(candidate_model_names):
            if model_name not in self.env.registry:
                continue
            record = self.env[model_name].browse(plan_id).exists()
            if record:
                return record
        return False

    def _wgs_get_plan_min_end_threshold(self, plan, start_date, periods_count=1):
        start_date = fields.Date.to_date(start_date) or fields.Date.context_today(self)
        interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)
        multiplier = max(1, int(periods_count or 1))
        interval_value = interval_value * multiplier
        if interval_unit == 'day':
            return start_date + timedelta(days=interval_value)
        if interval_unit == 'week':
            return start_date + relativedelta(weeks=interval_value)
        if interval_unit == 'year':
            return start_date + relativedelta(years=interval_value)
        return start_date + relativedelta(months=interval_value)

    def _wgs_get_plan_period_end_date(self, plan, start_date, periods_count=1):
        next_threshold = self._wgs_get_plan_min_end_threshold(plan, start_date, periods_count=periods_count)
        if not next_threshold:
            return False
        start_date = fields.Date.to_date(start_date) or fields.Date.context_today(self)
        period_end = fields.Date.to_date(next_threshold) - timedelta(days=1)
        if period_end < start_date:
            return start_date
        return period_end

    def _wgs_get_period_alignment_field_name(self, plan):
        if not plan:
            return False

        for field_name in self._WGS_PERIOD_ALIGNMENT_FIELD_NAMES:
            if field_name in plan._fields:
                return field_name

        for field_name, field in plan._fields.items():
            if field.type != 'boolean':
                continue
            normalized_name = (field_name or '').lower()
            normalized_label = (getattr(field, 'string', '') or '').lower()
            searchable = f'{normalized_name} {normalized_label}'
            if 'align' in searchable and ('period' in searchable or 'billing' in searchable or 'invoice' in searchable):
                return field_name
        return False

    def _wgs_plan_aligns_to_period_start(self, plan):
        field_name = self._wgs_get_period_alignment_field_name(plan)
        if not field_name:
            return False

        value = plan[field_name]
        if isinstance(value, bool):
            return value
        normalized = str(value or '').strip().lower()
        return normalized in ('1', 'true', 'yes', 'y', 'period_start', 'start', 'calendar', 'month_start')

    def _wgs_should_align_plan_to_calendar_month(self, plan):
        if not self._wgs_plan_aligns_to_period_start(plan):
            return False
        interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)
        return int(interval_value or 1) == 1 and (interval_unit or 'month') == 'month'

    def _wgs_product_is_direct_debit_membership(self, product):
        product = product.exists() if product else self.env['product.product']
        if not product:
            return False
        tmpl = product.product_tmpl_id if getattr(product, 'product_tmpl_id', False) else product
        return bool(getattr(product, 'wgs_direct_debit_membership', False) or getattr(tmpl, 'wgs_direct_debit_membership', False))

    def _wgs_month_start(self, value):
        value = fields.Date.to_date(value) or fields.Date.context_today(self)
        return value.replace(day=1)

    def _wgs_month_end(self, value):
        value = fields.Date.to_date(value) or fields.Date.context_today(self)
        return value + relativedelta(day=31)

    def _wgs_get_direct_debit_term_months(self, plan):
        interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)
        interval_value = max(1, int(interval_value or 1))
        if interval_unit == 'year':
            return interval_value * 12
        if interval_unit == 'month':
            return interval_value
        if interval_unit == 'week':
            return max(1, int(round((interval_value * 7) / 30.0)))
        return 1

    def _wgs_get_direct_debit_initial_schedule(self, plan, access_start_date, monthly_amount):
        access_start_date = fields.Date.to_date(access_start_date) or fields.Date.context_today(self)
        term_months = self._wgs_get_direct_debit_term_months(plan)
        term_start = self._wgs_month_start(access_start_date)
        first_month_end = self._wgs_month_end(access_start_date)
        term_end = term_start + relativedelta(months=term_months, days=-1)
        last_month_start = self._wgs_month_start(term_end)
        last_month_end = term_end

        period_days = max(1, (first_month_end - term_start).days + 1)
        charge_days = max(1, (first_month_end - access_start_date).days + 1)
        proration_ratio = min(charge_days, period_days) / float(period_days)
        first_month_charge = round(max(float(monthly_amount or 0.0) * proration_ratio, 0.0), 2)
        last_month_charge = 0.0 if last_month_start <= term_start else round(max(float(monthly_amount or 0.0), 0.0), 2)
        charge_now = round(first_month_charge + last_month_charge, 2)

        return {
            'direct_debit': True,
            'term_months': term_months,
            'term_start_date': term_start,
            'term_end_date': term_end,
            'paid_until_date': first_month_end,
            'last_month_start_date': last_month_start,
            'last_month_end_date': last_month_end,
            'subscription_start_date': term_start,
            'subscription_end_date': term_end,
            'next_billing_date': first_month_end + timedelta(days=1) if first_month_end < last_month_start else False,
            'access_start_date': access_start_date,
            'first_month_charge': first_month_charge,
            'last_month_charge': last_month_charge,
            'charge_now': charge_now,
            'period_days': period_days,
            'charge_days': min(charge_days, period_days),
            'proration_ratio': proration_ratio,
        }

    def _wgs_get_direct_debit_paid_until(self, source_order):
        source_order.ensure_one()
        paid_until = getattr(source_order, 'wgs_direct_debit_paid_until_date', False)
        if paid_until:
            return fields.Date.to_date(paid_until)
        next_date = self._wgs_get_first_date_from_order(source_order, ('recurring_next_date', 'next_invoice_date'))
        if next_date:
            return fields.Date.to_date(next_date) - timedelta(days=1)
        return False

    def _wgs_get_direct_debit_renewal_schedule(self, source_order, today=False, months_to_pay=False):
        source_order.ensure_one()
        today = fields.Date.to_date(today) or fields.Date.context_today(self)
        monthly_amount = round(max(float(getattr(source_order, 'wgs_direct_debit_monthly_amount', 0.0) or 0.0), 0.0), 2)
        term_end = fields.Date.to_date(getattr(source_order, 'wgs_direct_debit_term_end_date', False)) or self._wgs_get_first_date_from_order(
            source_order,
            ('end_date', 'date_end', 'subscription_end_date', 'recurring_end_date'),
        )
        last_start = fields.Date.to_date(getattr(source_order, 'wgs_direct_debit_last_month_start_date', False))
        paid_until = self._wgs_get_direct_debit_paid_until(source_order)
        if not paid_until:
            term_start = fields.Date.to_date(getattr(source_order, 'wgs_direct_debit_term_start_date', False)) or self._wgs_get_first_date_from_order(
                source_order,
                ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date', 'date_order'),
            ) or today
            paid_until = self._wgs_month_start(term_start) - timedelta(days=1)

        current_month_end = self._wgs_month_end(today)
        billable_end = current_month_end
        if term_end and billable_end > term_end:
            billable_end = term_end
        if last_start:
            last_prepaid_previous_day = last_start - timedelta(days=1)
            if billable_end > last_prepaid_previous_day:
                billable_end = last_prepaid_previous_day

        due_periods = []
        next_start = paid_until + timedelta(days=1)
        if next_start.day != 1:
            next_start = self._wgs_month_start(next_start)
        while billable_end and next_start <= billable_end:
            period_end = self._wgs_month_end(next_start)
            if period_end > billable_end:
                period_end = billable_end
            due_periods.append({
                'start_date': next_start,
                'end_date': period_end,
                'amount': monthly_amount,
            })
            next_start = period_end + timedelta(days=1)

        due_count = len(due_periods)
        try:
            selected_count = int(months_to_pay or due_count)
        except (TypeError, ValueError):
            selected_count = due_count
        selected_count = min(max(selected_count, 0), due_count)
        selected_periods = due_periods[:selected_count]
        resulting_paid_until = selected_periods[-1]['end_date'] if selected_periods else paid_until
        access_restored = False
        if resulting_paid_until >= current_month_end:
            access_restored = True
        elif last_start and term_end and last_start <= today <= term_end:
            access_restored = resulting_paid_until >= (last_start - timedelta(days=1))

        next_billing_date = resulting_paid_until + timedelta(days=1) if selected_periods else paid_until + timedelta(days=1)
        if last_start and next_billing_date >= last_start:
            next_billing_date = False

        return {
            'direct_debit': True,
            'monthly_amount': monthly_amount,
            'due_periods': due_periods,
            'due_month_count': due_count,
            'selected_month_count': selected_count,
            'amount_due_total': round(sum(period['amount'] for period in due_periods), 2),
            'amount_to_pay': round(sum(period['amount'] for period in selected_periods), 2),
            'paid_until_date': paid_until,
            'resulting_paid_until_date': resulting_paid_until,
            'current_month_end_date': current_month_end,
            'next_billing_date': next_billing_date,
            'access_restored': access_restored,
            'term_end_date': term_end,
            'last_month_start_date': last_start,
        }

    def _wgs_get_aligned_monthly_first_period_schedule(self, start_date):
        access_start_date = fields.Date.to_date(start_date) or fields.Date.context_today(self)
        period_start = access_start_date.replace(day=1)
        next_billing_date = period_start + relativedelta(months=1)
        period_end = next_billing_date - timedelta(days=1)
        period_days = max(1, (next_billing_date - period_start).days)
        charge_days = max(1, (period_end - access_start_date).days + 1)
        return {
            'subscription_start_date': period_start,
            'subscription_end_date': period_end,
            'next_billing_date': next_billing_date,
            'period_start_date': period_start,
            'access_start_date': access_start_date,
            'period_days': period_days,
            'charge_days': min(charge_days, period_days),
            'proration_ratio': min(charge_days, period_days) / float(period_days),
        }

    def _wgs_get_subscription_renewal_schedule(self, source_order, today=False, preferred_line=False):
        source_order.ensure_one()
        today = fields.Date.to_date(today) or fields.Date.context_today(self)
        preferred_line = preferred_line.exists() if preferred_line else self.env['sale.order.line']
        plan = self._wgs_extract_plan_record_from_subscription_line(preferred_line)
        if not plan:
            plan = self._wgs_extract_plan_record_from_sale_order(source_order)

        _period_start, period_end = self._wgs_get_current_subscription_period_bounds(
            source_order,
            today=today,
            preferred_line=preferred_line,
        )
        renewal_anchor = period_end if period_end and today < period_end else today

        if self._wgs_should_align_plan_to_calendar_month(plan):
            aligned_schedule = self._wgs_get_aligned_monthly_first_period_schedule(renewal_anchor)
            return {
                'renewal_anchor': renewal_anchor,
                'subscription_end_date': aligned_schedule['subscription_end_date'],
                'next_billing_date': aligned_schedule['next_billing_date'],
                'period_aligned': True,
            }

        next_billing_date = renewal_anchor + self._wgs_get_order_recurrence_delta(
            source_order,
            preferred_line=preferred_line,
        )
        return {
            'renewal_anchor': renewal_anchor,
            'subscription_end_date': fields.Date.to_date(next_billing_date) - timedelta(days=1),
            'next_billing_date': next_billing_date,
            'period_aligned': False,
        }

    def _wgs_extract_interval_from_plan(self, plan):
        interval_value = 1
        interval_unit = 'month'
        if not plan:
            return interval_value, interval_unit

        if 'wgs_single_day_plan' in plan._fields and plan.wgs_single_day_plan:
            return 1, 'day'

        if {'recurring_interval', 'recurring_rule_type'}.issubset(plan._fields):
            interval_value = int(plan.recurring_interval or 1)
            interval_unit = plan.recurring_rule_type or 'month'
        elif {'billing_period_value', 'billing_period_unit'}.issubset(plan._fields):
            interval_value = int(plan.billing_period_value or 1)
            interval_unit = plan.billing_period_unit or 'month'
        elif {'interval_number', 'interval_type'}.issubset(plan._fields):
            interval_value = int(plan.interval_number or 1)
            interval_unit = plan.interval_type or 'month'
        elif {'duration', 'duration_unit'}.issubset(plan._fields):
            interval_value = int(plan.duration or 1)
            interval_unit = plan.duration_unit or 'month'

        interval_value = max(1, int(interval_value or 1))
        interval_unit = (interval_unit or 'month').lower()
        if 'day' in interval_unit:
            return interval_value, 'day'
        if 'quinc' in interval_unit:
            return interval_value * 2, 'week'
        if 'week' in interval_unit:
            return interval_value, 'week'
        if 'year' in interval_unit or 'annual' in interval_unit:
            return interval_value, 'year'
        return interval_value, 'month'

    def _wgs_is_plan_model_name(self, model_name):
        model_name = (model_name or '').lower()
        if not model_name:
            return False
        if 'subscription.plan' in model_name or 'recurring.plan' in model_name:
            return True
        if 'recurr' in model_name:
            return True
        if 'subscription' in model_name and ('period' in model_name or 'template' in model_name):
            return True
        return model_name.endswith('.plan')

    def _wgs_is_pricing_model_name(self, model_name):
        model_name = (model_name or '').lower()
        if not model_name:
            return False
        if 'subscription.pricing' in model_name or 'recurring.pricing' in model_name:
            return True
        return 'subscription' in model_name and 'price' in model_name

    def _wgs_build_product_pricing_snapshot(
        self,
        product,
        *,
        flow='new',
        fallback=0.0,
        preferred_plan_id=False,
        preferred_pricing_id=False,
        partner=False,
        company=False,
        fiscal_position=False,
        source_order=False,
        source_subscription_id=False,
        include_credit=False,
        start_date=False,
    ):
        product.ensure_one()
        pricing_resolution = self._wgs_resolve_recurring_pricing(
            product,
            fallback=fallback,
            preferred_plan_id=preferred_plan_id,
            preferred_pricing_id=preferred_pricing_id,
        )
        choice = dict(pricing_resolution.get('choice') or {})
        recurring_price = round(max(float(choice.get('price') or 0.0), 0.0), 2)
        display_recurring_price = self._wgs_get_price_with_taxes_for_pos(
            product,
            recurring_price,
            partner=partner or False,
            company=company or False,
            fiscal_position=fiscal_position or False,
        )
        resolved_plan = self._wgs_resolve_plan_record(
            product,
            plan_id=choice.get('plan_id') or preferred_plan_id,
            pricing_id=choice.get('pricing_id') or preferred_pricing_id,
        )
        source_order = source_order.exists() if source_order else self.env['sale.order']
        credit_amount = 0.0
        display_credit_amount = 0.0
        subscription_start_date = False
        subscription_end_date = False
        next_billing_date = False
        first_period_alignment = {}
        direct_debit_schedule = {}
        if include_credit and source_order:
            credit_amount = self._wgs_get_upsale_source_recurring_amount(source_order)
            display_credit_amount = self._wgs_get_upsale_source_recurring_amount(
                source_order,
                tax_included=True,
            )
            upsale_schedule = self._wgs_get_upsale_schedule_from_source(source_order)
            subscription_start_date = upsale_schedule.get('subscription_start_date') or False
            subscription_end_date = upsale_schedule.get('subscription_end_date') or False
            next_billing_date = upsale_schedule.get('next_billing_date') or False
        charge_now = round(max(recurring_price - credit_amount, 0.0), 2)
        if include_credit and source_order:
            display_charge_now = round(max(display_recurring_price - display_credit_amount, 0.0), 2)
        else:
            if flow in ('new', 'reenroll') and self._wgs_product_is_direct_debit_membership(product):
                direct_debit_schedule = self._wgs_get_direct_debit_initial_schedule(
                    resolved_plan,
                    start_date or fields.Date.context_today(self),
                    recurring_price,
                )
                subscription_start_date = direct_debit_schedule['subscription_start_date']
                subscription_end_date = direct_debit_schedule['subscription_end_date']
                next_billing_date = direct_debit_schedule['next_billing_date']
                charge_now = direct_debit_schedule['charge_now']
                first_period_alignment = {
                    'period_start_date': direct_debit_schedule['term_start_date'],
                    'access_start_date': direct_debit_schedule['access_start_date'],
                    'period_days': direct_debit_schedule['period_days'],
                    'charge_days': direct_debit_schedule['charge_days'],
                }
            elif flow in ('new', 'reenroll') and self._wgs_should_align_plan_to_calendar_month(resolved_plan):
                first_period_alignment = self._wgs_get_aligned_monthly_first_period_schedule(
                    start_date or fields.Date.context_today(self)
                )
                subscription_start_date = first_period_alignment['subscription_start_date']
                subscription_end_date = first_period_alignment['subscription_end_date']
                next_billing_date = first_period_alignment['next_billing_date']
                charge_now = round(max(recurring_price * first_period_alignment['proration_ratio'], 0.0), 2)
            display_charge_now = self._wgs_get_price_with_taxes_for_pos(
                product,
                charge_now,
                partner=partner or False,
                company=company or False,
                fiscal_position=fiscal_position or False,
            )
        return {
            'mode': 'product',
            'flow': flow,
            'product_id': product.id,
            'product_name': product.display_name,
            'plan_id': choice.get('plan_id') or False,
            'plan_name': choice.get('plan_name') or False,
            'pricing_id': choice.get('pricing_id') or False,
            'price_unit': recurring_price,
            'display_price_unit': float(display_recurring_price),
            'ticket_price_unit': recurring_price,
            'credit_amount': float(credit_amount),
            'display_credit_amount': float(display_credit_amount),
            'ticket_credit_amount': float(credit_amount),
            'charge_now': float(charge_now),
            'display_charge_now': float(display_charge_now),
            'ticket_charge_now': float(charge_now),
            'subscription_start_date': fields.Date.to_string(subscription_start_date) if subscription_start_date else False,
            'subscription_end_date': fields.Date.to_string(subscription_end_date) if subscription_end_date else False,
            'next_billing_date': fields.Date.to_string(next_billing_date) if next_billing_date else False,
            'first_period_alignment': bool(first_period_alignment),
            'first_period_start_date': (
                fields.Date.to_string(first_period_alignment['period_start_date'])
                if first_period_alignment else False
            ),
            'first_period_access_start_date': (
                fields.Date.to_string(first_period_alignment['access_start_date'])
                if first_period_alignment else False
            ),
            'first_period_days': int(first_period_alignment.get('period_days') or 0) if first_period_alignment else 0,
            'first_period_charge_days': int(first_period_alignment.get('charge_days') or 0) if first_period_alignment else 0,
            'direct_debit': bool(direct_debit_schedule),
            'direct_debit_term_months': int(direct_debit_schedule.get('term_months') or 0),
            'direct_debit_monthly_amount': float(recurring_price) if direct_debit_schedule else 0.0,
            'direct_debit_first_month_charge': float(direct_debit_schedule.get('first_month_charge') or 0.0),
            'direct_debit_last_month_charge': float(direct_debit_schedule.get('last_month_charge') or 0.0),
            'direct_debit_paid_until_date': (
                fields.Date.to_string(direct_debit_schedule['paid_until_date'])
                if direct_debit_schedule else False
            ),
            'direct_debit_term_start_date': (
                fields.Date.to_string(direct_debit_schedule['term_start_date'])
                if direct_debit_schedule else False
            ),
            'direct_debit_term_end_date': (
                fields.Date.to_string(direct_debit_schedule['term_end_date'])
                if direct_debit_schedule else False
            ),
            'direct_debit_last_month_start_date': (
                fields.Date.to_string(direct_debit_schedule['last_month_start_date'])
                if direct_debit_schedule else False
            ),
            'direct_debit_last_month_end_date': (
                fields.Date.to_string(direct_debit_schedule['last_month_end_date'])
                if direct_debit_schedule else False
            ),
            'source_recurring_price': float(credit_amount),
            'source_display_recurring_price': float(display_credit_amount),
            'interval_value': int(choice.get('interval_value') or 1),
            'interval_unit': choice.get('interval_unit') or 'month',
            'interval_label': choice.get('interval_label') or '',
            'candidates': list(pricing_resolution.get('candidates') or []),
            'choice': choice,
            'source': {
                'type': 'subscription_pricing' if choice.get('pricing_id') else 'fallback',
                'id': choice.get('pricing_id') or False,
                'subscription_id': source_subscription_id or (source_order.id if source_order else False),
                'subscription_name': source_order.name if source_order else False,
            },
            'context': {
                'fallback': float(fallback or 0.0),
                'preferred_plan_id': int(preferred_plan_id or 0),
                'preferred_pricing_id': int(preferred_pricing_id or 0),
                'include_credit': bool(include_credit),
            },
        }

    def _wgs_extract_subscription_ids_from_line(self, recurring_line):
        recurring_line.ensure_one()
        plan_id = False
        pricing_id = False
        for field_name in self._WGS_PLAN_FIELD_NAMES:
            if field_name in recurring_line._fields and recurring_line[field_name]:
                plan_id = recurring_line[field_name].id
                break
        for field_name in self._WGS_PRICING_FIELD_NAMES:
            if field_name in recurring_line._fields and recurring_line[field_name]:
                pricing_id = recurring_line[field_name].id
                break
        return plan_id, pricing_id

    def _wgs_build_subscription_line_pricing_snapshot(
        self,
        source_order,
        *,
        flow='renewal',
        product_id=False,
        preferred_plan_id=False,
        preferred_pricing_id=False,
    ):
        source_order.ensure_one()
        recurring_lines = source_order.order_line.filtered(lambda so_line: self._wgs_is_recurring_so_line(so_line))
        if not recurring_lines:
            raise ValueError('Source order has no recurring lines.')

        try:
            preferred_product_id = int(product_id or 0)
        except (TypeError, ValueError):
            preferred_product_id = 0
        recurring_line = self.env['sale.order.line']
        if preferred_product_id > 0:
            recurring_line = recurring_lines.filtered(lambda so_line: so_line.product_id.id == preferred_product_id)[:1]
        if not recurring_line:
            recurring_line = recurring_lines.sorted(key=lambda so_line: so_line.id)[:1]
        if not recurring_line:
            raise ValueError('Source order has no recurring line after selection.')

        recurring_price = self._wgs_get_order_recurring_total_amount(source_order)
        display_recurring_price = self._wgs_get_order_recurring_total_amount(source_order, include_taxes=True)
        qty = abs(self._wgs_get_so_line_qty(recurring_line))
        discount = float(recurring_line.discount or 0.0) if 'discount' in recurring_line._fields else 0.0
        recurring_price = qty * float(recurring_line.price_unit or 0.0) * (1 - (discount / 100.0))
        display_recurring_price = self._wgs_get_sale_order_line_total_with_tax(recurring_line, qty_override=qty)
        recurring_price = round(max(float(recurring_price or 0.0), 0.0), 2)
        display_recurring_price = round(max(float(display_recurring_price or 0.0), 0.0), 2)

        plan_id, pricing_id = self._wgs_extract_subscription_ids_from_line(recurring_line)
        try:
            preferred_plan_id = int(preferred_plan_id or 0)
        except (TypeError, ValueError):
            preferred_plan_id = 0
        try:
            preferred_pricing_id = int(preferred_pricing_id or 0)
        except (TypeError, ValueError):
            preferred_pricing_id = 0
        resolved_plan_id = preferred_plan_id or plan_id or False
        resolved_pricing_id = preferred_pricing_id or pricing_id or False
        resolved_plan_record = self._wgs_find_plan_record_by_id(resolved_plan_id) if resolved_plan_id else self._wgs_extract_plan_record_from_sale_order(source_order)
        interval_value, interval_unit = self._wgs_extract_interval_from_plan(resolved_plan_record)
        renewal_schedule = self._wgs_get_subscription_renewal_schedule(
            source_order,
            preferred_line=recurring_line,
        )
        direct_debit_schedule = {}
        if getattr(source_order, 'wgs_direct_debit_subscription', False):
            direct_debit_schedule = self._wgs_get_direct_debit_renewal_schedule(source_order)
            renewal_schedule = {
                'renewal_anchor': direct_debit_schedule.get('paid_until_date') or fields.Date.context_today(self),
                'subscription_end_date': direct_debit_schedule.get('term_end_date') or renewal_schedule['subscription_end_date'],
                'next_billing_date': direct_debit_schedule.get('next_billing_date') or False,
                'period_aligned': True,
            }
            recurring_price = float(direct_debit_schedule.get('monthly_amount') or recurring_price)
            display_recurring_price = self._wgs_get_sale_order_line_total_with_tax(recurring_line, qty_override=qty)
            direct_debit_charge = float(direct_debit_schedule.get('amount_due_total') or 0.0)
            direct_debit_display_charge = self._wgs_get_price_with_taxes_for_pos(
                recurring_line.product_id,
                direct_debit_charge,
                partner=source_order.partner_id,
                company=source_order.company_id if 'company_id' in source_order._fields else False,
                fiscal_position=source_order.fiscal_position_id if 'fiscal_position_id' in source_order._fields else False,
            )
        else:
            direct_debit_charge = recurring_price
            direct_debit_display_charge = display_recurring_price
        return {
            'mode': 'subscription',
            'flow': flow,
            'product_id': recurring_line.product_id.id,
            'product_name': recurring_line.product_id.display_name,
            'plan_id': resolved_plan_id,
            'plan_name': resolved_plan_record.display_name if resolved_plan_record else False,
            'pricing_id': resolved_pricing_id,
            'price_unit': float(recurring_price),
            'display_price_unit': float(display_recurring_price),
            'ticket_price_unit': float(recurring_price),
            'credit_amount': 0.0,
            'display_credit_amount': 0.0,
            'ticket_credit_amount': 0.0,
            'charge_now': float(direct_debit_charge),
            'display_charge_now': float(direct_debit_display_charge),
            'ticket_charge_now': float(direct_debit_charge),
            'subscription_start_date': fields.Date.to_string(renewal_schedule['renewal_anchor']),
            'subscription_end_date': fields.Date.to_string(renewal_schedule['subscription_end_date']),
            'next_billing_date': fields.Date.to_string(renewal_schedule['next_billing_date']) if renewal_schedule.get('next_billing_date') else False,
            'first_period_alignment': bool(renewal_schedule.get('period_aligned')),
            'direct_debit': bool(direct_debit_schedule),
            'direct_debit_monthly_amount': float(direct_debit_schedule.get('monthly_amount') or 0.0),
            'direct_debit_due_month_count': int(direct_debit_schedule.get('due_month_count') or 0),
            'direct_debit_months_to_pay': int(direct_debit_schedule.get('due_month_count') or 0),
            'direct_debit_amount_due_total': float(direct_debit_schedule.get('amount_due_total') or 0.0),
            'direct_debit_paid_until_date': (
                fields.Date.to_string(direct_debit_schedule['paid_until_date'])
                if direct_debit_schedule and direct_debit_schedule.get('paid_until_date') else False
            ),
            'direct_debit_resulting_paid_until_date': (
                fields.Date.to_string(direct_debit_schedule['resulting_paid_until_date'])
                if direct_debit_schedule and direct_debit_schedule.get('resulting_paid_until_date') else False
            ),
            'direct_debit_current_month_end_date': (
                fields.Date.to_string(direct_debit_schedule['current_month_end_date'])
                if direct_debit_schedule and direct_debit_schedule.get('current_month_end_date') else False
            ),
            'direct_debit_access_restored': bool(direct_debit_schedule.get('access_restored')) if direct_debit_schedule else False,
            'direct_debit_due_periods': [
                {
                    'start_date': fields.Date.to_string(period['start_date']),
                    'end_date': fields.Date.to_string(period['end_date']),
                    'amount': float(period.get('amount') or 0.0),
                }
                for period in direct_debit_schedule.get('due_periods', [])
            ] if direct_debit_schedule else [],
            'interval_value': int(interval_value or 1),
            'interval_unit': interval_unit or 'month',
            'interval_label': f'{int(interval_value or 1)} {interval_unit or "month"}',
            'candidates': [],
            'choice': {
                'plan_id': resolved_plan_id,
                'pricing_id': resolved_pricing_id,
                'price': float(recurring_price),
            },
            'source': {
                'type': 'subscription_line',
                'id': recurring_line.id,
                'subscription_id': source_order.id,
                'subscription_name': source_order.name,
            },
            'context': {
                'preferred_plan_id': int(preferred_plan_id or 0),
                'preferred_pricing_id': int(preferred_pricing_id or 0),
            },
            'source_order': source_order,
            'source_line': recurring_line,
        }

    def _wgs_resolve_subscription_pricing_snapshot(
        self,
        *,
        flow='new',
        product=False,
        partner=False,
        company=False,
        fiscal_position=False,
        source_order=False,
        fallback=0.0,
        preferred_plan_id=False,
        preferred_pricing_id=False,
        include_credit=False,
        start_date=False,
    ):
        source_order = source_order.exists() if source_order else self.env['sale.order']
        if flow == 'renewal':
            if not source_order:
                raise ValueError('Subscription snapshot requires source order.')
            return self._wgs_build_subscription_line_pricing_snapshot(
                source_order,
                flow=flow,
                product_id=product.id if product else False,
                preferred_plan_id=preferred_plan_id,
                preferred_pricing_id=preferred_pricing_id,
            )
        if not product:
            raise ValueError('Product-based snapshot requires a product.')
        product.ensure_one()
        return self._wgs_build_product_pricing_snapshot(
            product,
            flow=flow,
            fallback=fallback,
            preferred_plan_id=preferred_plan_id,
            preferred_pricing_id=preferred_pricing_id,
            partner=partner,
            company=company,
            fiscal_position=fiscal_position,
            source_order=source_order,
            source_subscription_id=source_order.id if source_order else False,
            include_credit=include_credit,
            start_date=start_date,
        )

    def _wgs_extract_plan_id_from_product(self, product):
        plan = self._wgs_extract_plan_record_from_product(product)
        return plan.id if plan else False

    def _wgs_extract_plan_record_from_product(self, product):
        product.ensure_one()

        if self._wgs_is_plan_model_name(product._name):
            return product
        if self._wgs_is_plan_model_name(product.product_tmpl_id._name):
            return product.product_tmpl_id

        for source in (product, product.product_tmpl_id):
            for field_name in self._WGS_PLAN_FIELD_NAMES:
                if field_name in source._fields and source[field_name]:
                    return source[field_name]

        for source in (product, product.product_tmpl_id):
            for field_name, field in source._fields.items():
                if field.type not in ('many2one', 'one2many', 'many2many'):
                    continue
                comodel_name = getattr(field, 'comodel_name', '')
                normalized_name = (field_name or '').lower()
                is_candidate_name = (
                    ('plan' in normalized_name)
                    or ('recurr' in normalized_name)
                    or ('period' in normalized_name)
                )
                if not (self._wgs_is_plan_model_name(comodel_name) or is_candidate_name):
                    continue
                value = source[field_name]
                if not value:
                    continue
                if field.type == 'many2one':
                    return value
                return value[:1]
        return False

    def _wgs_select_recurring_pricing_choice(
        self,
        candidates,
        *,
        fallback=0.0,
        preferred_plan_id=False,
        preferred_pricing_id=False,
    ):
        fallback_price = float(fallback or 0.0)
        candidates = list(candidates or [])
        if not candidates:
            return {
                'price': fallback_price,
                'plan_id': False,
                'pricing_id': False,
            }
        preferred_plan_id = int(preferred_plan_id or 0)
        preferred_pricing_id = int(preferred_pricing_id or 0)
        if preferred_pricing_id:
            matching = [row for row in candidates if int(row.get('pricing_id') or 0) == preferred_pricing_id]
            if matching:
                return matching[0]
        if preferred_plan_id:
            matching = [row for row in candidates if int(row.get('plan_id') or 0) == preferred_plan_id]
            if matching:
                matching.sort(key=lambda row: (row['sequence'], row.get('pricing_id') or 0))
                return matching[0]

        candidates.sort(key=lambda row: (row['sequence'], row.get('pricing_id') or 0))
        return candidates[0]

    def _wgs_resolve_recurring_pricing(
        self,
        product,
        *,
        fallback=0.0,
        preferred_plan_id=False,
        preferred_pricing_id=False,
    ):
        product.ensure_one()
        candidates = self._wgs_get_recurring_pricing_candidates(product)
        choice = self._wgs_select_recurring_pricing_choice(
            candidates,
            fallback=fallback,
            preferred_plan_id=preferred_plan_id,
            preferred_pricing_id=preferred_pricing_id,
        )
        return {
            'candidates': candidates,
            'choice': choice,
        }

    def _wgs_get_direct_subscription_pricing_records(self, product):
        product.ensure_one()
        model_name = 'sale.subscription.pricing'
        if model_name not in self.env.registry:
            return ()

        cache = self._wgs_get_env_cache('_wgs_direct_subscription_pricing_records_cache')
        cache_key = (product._name, product.id, product.product_tmpl_id.id)
        if cache_key in cache:
            return cache[cache_key]

        records = self.env[model_name].browse()
        for source in (product, product.product_tmpl_id):
            relation_field_names = self._wgs_get_relation_field_names(
                source._name,
                model_name,
                relation_types=('many2one', 'one2many', 'many2many'),
                preferred_field_names=self._WGS_PRODUCT_PRICING_RELATION_FIELD_NAMES,
            )
            for field_name in relation_field_names:
                field = source._fields.get(field_name)
                if not field:
                    continue
                value = source[field_name]
                if not value:
                    continue
                records |= value if field.type in ('one2many', 'many2many') else value.exists()
        result = tuple(records)
        cache[cache_key] = result
        return result

    def _wgs_search_related_records(
        self,
        model_name,
        *,
        product=False,
        template=False,
        product_field_names=(),
        template_field_names=(),
    ):
        if model_name not in self.env.registry:
            return ()

        cache = self._wgs_get_env_cache('_wgs_search_related_records_cache')
        cache_key = (
            model_name,
            product.id if product else 0,
            template.id if template else 0,
            tuple(product_field_names or ()),
            tuple(template_field_names or ()),
        )
        if cache_key in cache:
            return cache[cache_key]

        model = self.env[model_name]
        product_field_names = self._wgs_get_relation_field_names(
            model_name,
            'product.product',
            relation_types=('many2one',),
            preferred_field_names=product_field_names,
        )
        template_field_names = self._wgs_get_relation_field_names(
            model_name,
            'product.template',
            relation_types=('many2one',),
            preferred_field_names=template_field_names,
        )
        domain_parts = []
        if product:
            domain_parts.extend([[(field_name, '=', product.id)] for field_name in product_field_names])
        if template:
            domain_parts.extend([[(field_name, '=', template.id)] for field_name in template_field_names])
        if not domain_parts:
            result = ()
        else:
            result = tuple(
                model.search(
                    fields.Domain.OR(
                        fields.Domain(domain_part)
                        for domain_part in domain_parts
                    )
                )
            )
        cache[cache_key] = result
        return result

    def _wgs_get_recurring_pricing_candidates(self, product):
        product.ensure_one()
        cache = getattr(self.env, '_wgs_recurring_pricing_candidates_cache', None)
        if cache is None:
            cache = {}
            setattr(self.env, '_wgs_recurring_pricing_candidates_cache', cache)
        cache_key = (product._name, product.id, product.product_tmpl_id.id)
        if cache_key in cache:
            return [dict(candidate) for candidate in cache[cache_key]]

        candidates = []
        seen_pricing_ids = set()

        # Resolve candidates in an explicit strategy order so the path stays
        # predictable and cheaper to reason about.
        for pricing in self._wgs_get_direct_subscription_pricing_records(product):
            if pricing.id in seen_pricing_ids:
                continue
            candidate = self._wgs_build_pricing_candidate(pricing)
            if not candidate:
                continue
            seen_pricing_ids.add(pricing.id)
            candidates.append(candidate)

        for candidate in self._wgs_search_subscription_pricing_records(product):
            pricing_id = int(candidate.get('pricing_id') or 0)
            if pricing_id and pricing_id in seen_pricing_ids:
                continue
            if pricing_id:
                seen_pricing_ids.add(pricing_id)
            candidates.append(candidate)

        if not candidates:
            candidates.extend(self._wgs_search_product_pricelist_item_records(product))

        if not candidates:
            _logger.warning(
                'WGS POS: No recurring pricing candidates for product %s (id=%s). recurring_invoice=%s',
                product.display_name,
                product.id,
                bool(getattr(product.product_tmpl_id, 'recurring_invoice', False)),
            )

        normalized_candidates = self._wgs_normalize_recurring_pricing_candidates(candidates)
        cache[cache_key] = [dict(candidate) for candidate in normalized_candidates]
        return [dict(candidate) for candidate in normalized_candidates]

    def _wgs_normalize_recurring_pricing_candidates(self, candidates):
        if not candidates:
            return []

        best_by_key = {}
        for candidate in candidates:
            plan_id = int(candidate.get('plan_id') or 0)
            pricing_id = int(candidate.get('pricing_id') or 0)
            key = ('plan', plan_id) if plan_id else ('pricing', pricing_id)
            current = best_by_key.get(key)
            if not current:
                best_by_key[key] = candidate
                continue

            current_has_pricing = bool(int(current.get('pricing_id') or 0))
            candidate_has_pricing = bool(pricing_id)
            current_sequence = int(current.get('sequence') or 0)
            candidate_sequence = int(candidate.get('sequence') or 0)

            should_replace = False
            if candidate_has_pricing and not current_has_pricing:
                should_replace = True
            elif candidate_has_pricing == current_has_pricing:
                if candidate_sequence < current_sequence:
                    should_replace = True
                elif candidate_sequence == current_sequence and pricing_id and pricing_id < int(current.get('pricing_id') or 0):
                    should_replace = True

            if should_replace:
                best_by_key[key] = candidate

        output = list(best_by_key.values())
        output.sort(key=lambda row: (int(row.get('sequence') or 0), int(row.get('pricing_id') or 0), int(row.get('plan_id') or 0)))
        return output

    def _wgs_search_product_pricelist_item_records(self, product):
        model_name = 'product.pricelist.item'
        if model_name not in self.env.registry:
            return []

        records = self._wgs_search_related_records(
            model_name,
            product=product,
            template=product.product_tmpl_id,
            product_field_names=self._WGS_PRICELIST_ITEM_PRODUCT_FIELD_NAMES,
            template_field_names=self._WGS_PRICELIST_ITEM_TEMPLATE_FIELD_NAMES,
        )

        output = []
        seen = set()
        for record in records:
            if record.id in seen:
                continue
            seen.add(record.id)

            plan = self._wgs_extract_plan_record_from_pricing(record)
            if not plan:
                continue

            price = self._wgs_extract_price_from_pricing(record)
            if price is None:
                continue
            interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)

            output.append({
                'sequence': self._wgs_extract_pricing_sequence(record),
                'pricing_id': False,
                'plan_id': plan.id,
                'plan_name': plan.display_name,
                'interval_label': self._wgs_extract_plan_interval_label_from_pricing(record),
                'interval_value': interval_value,
                'interval_unit': interval_unit,
                'price': float(price),
            })
        return output

    def _wgs_build_pricing_candidate(self, pricing):
        plan = self._wgs_extract_plan_record_from_pricing(pricing)
        price = self._wgs_extract_price_from_pricing(pricing)
        if price is None:
            return False
        interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)
        return {
            'sequence': self._wgs_extract_pricing_sequence(pricing),
            'pricing_id': pricing.id,
            'plan_id': plan.id if plan else False,
            'plan_name': plan.display_name if plan else False,
            'interval_label': self._wgs_extract_plan_interval_label_from_pricing(pricing),
            'interval_value': interval_value,
            'interval_unit': interval_unit,
            'price': float(price),
        }

    def _wgs_search_subscription_pricing_records(self, product):
        pricing_model_name = 'sale.subscription.pricing'
        if pricing_model_name not in self.env.registry:
            return []

        records = self._wgs_search_related_records(
            pricing_model_name,
            product=product,
            template=product.product_tmpl_id,
            product_field_names=self._WGS_SUBSCRIPTION_PRICING_PRODUCT_FIELD_NAMES,
            template_field_names=self._WGS_SUBSCRIPTION_PRICING_TEMPLATE_FIELD_NAMES,
        )

        seen = set()
        output = []
        for pricing in records:
            if pricing.id in seen:
                continue
            seen.add(pricing.id)
            plan = self._wgs_extract_plan_record_from_pricing(pricing)
            price = self._wgs_extract_price_from_pricing(pricing)
            if price is None:
                continue
            interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)
            output.append({
                'sequence': self._wgs_extract_pricing_sequence(pricing),
                'pricing_id': pricing.id,
                'plan_id': plan.id if plan else False,
                'plan_name': plan.display_name if plan else False,
                'interval_label': self._wgs_extract_plan_interval_label_from_pricing(pricing),
                'interval_value': interval_value,
                'interval_unit': interval_unit,
                'price': float(price),
            })
        return output

    def _wgs_extract_plan_id_from_pricing(self, pricing):
        plan = self._wgs_extract_plan_record_from_pricing(pricing)
        if plan:
            return plan.id
        return False

    def _wgs_extract_plan_name_from_pricing(self, pricing):
        plan = self._wgs_extract_plan_record_from_pricing(pricing)
        if plan:
            return plan.display_name
        return False

    def _wgs_extract_plan_interval_label_from_pricing(self, pricing):
        plan = self._wgs_extract_plan_record_from_pricing(pricing)
        if not plan:
            return ''
        interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)
        return f'{interval_value} {interval_unit}'

    def _wgs_extract_plan_record_from_pricing(self, pricing):
        if self._wgs_is_plan_model_name(pricing._name):
            return pricing

        for field_name in self._WGS_PLAN_FIELD_NAMES:
            if field_name in pricing._fields and pricing[field_name]:
                return pricing[field_name]

        for field_name, field in pricing._fields.items():
            if field.type not in ('many2one', 'one2many', 'many2many'):
                continue
            comodel_name = getattr(field, 'comodel_name', '')
            normalized_name = (field_name or '').lower()
            is_candidate_name = (
                ('plan' in normalized_name)
                or ('recurr' in normalized_name)
                or ('period' in normalized_name)
            )
            if not (self._wgs_is_plan_model_name(comodel_name) or is_candidate_name):
                continue
            value = pricing[field_name]
            if not value:
                continue
            if field.type == 'many2one':
                return value
            return value[:1]
        return False

    def _wgs_extract_price_from_pricing(self, pricing):
        known_price_fields = (
            'fixed_price',
            'price',
            'recurring_price',
            'price_unit',
            'unit_price',
            'list_price',
            'amount',
        )
        for field_name in known_price_fields:
            if field_name not in pricing._fields:
                continue
            value = pricing[field_name]
            if value is not None:
                return float(value)

        for field_name, field in pricing._fields.items():
            if field_name in known_price_fields:
                continue
            if field.type not in ('float', 'monetary'):
                continue
            normalized_name = field_name.lower()
            if 'price' not in normalized_name and 'amount' not in normalized_name:
                continue
            value = pricing[field_name]
            if value is not None:
                return float(value)
        return None

    def _wgs_extract_pricing_sequence(self, pricing):
        if 'sequence' in pricing._fields and pricing.sequence is not None:
            return int(pricing.sequence)
        plan = self._wgs_extract_plan_record_from_pricing(pricing)
        if plan and 'sequence' in plan._fields:
            return int(plan.sequence or 1000)
        return 1000
