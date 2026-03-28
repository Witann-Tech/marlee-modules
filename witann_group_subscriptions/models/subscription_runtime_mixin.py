import logging
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields, models
from odoo.fields import Command

_logger = logging.getLogger(__name__)


class WgsSubscriptionRuntimeMixin(models.AbstractModel):
    _name = 'wgs.subscription.runtime.mixin'
    _description = 'WGS Subscription Runtime Helpers'

    def _wgs_to_date(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return fields.Date.to_date(value)

    def _wgs_convert_date_for_field_value(self, date_value, field):
        date_value = fields.Date.to_date(date_value)
        if not date_value:
            return False
        if field and field.type == 'datetime':
            return fields.Datetime.to_datetime(date_value)
        return date_value

    def _wgs_assign_many2one_value(self, values, fields_map, value_id, preferred_field_names=(), comodel_checker=None):
        value_id = int(value_id or 0)
        if value_id <= 0:
            return

        for field_name in preferred_field_names:
            field = fields_map.get(field_name)
            if field and field.type == 'many2one':
                values[field_name] = value_id
                return

        if not comodel_checker:
            return

        for field_name, field in fields_map.items():
            if field_name in values or field.type != 'many2one':
                continue
            normalized_name = (field_name or '').lower()
            heuristic_name_match = (
                ('plan' in normalized_name)
                or ('recurr' in normalized_name)
                or ('period' in normalized_name)
                or ('pricing' in normalized_name)
                or ('price' in normalized_name)
            )
            if comodel_checker(getattr(field, 'comodel_name', '')) or heuristic_name_match:
                values[field_name] = value_id
                return

    def _wgs_assign_date_field(self, values, fields_map, date_value, preferred_field_names=()):
        if not date_value:
            return
        for field_name in preferred_field_names:
            field = fields_map.get(field_name)
            if field and field.type in ('date', 'datetime'):
                values[field_name] = self._wgs_convert_date_for_field_value(date_value, field)
                return

    def _wgs_field_is_directly_writable(self, field):
        if not field:
            return False
        compute_name = getattr(field, 'compute', False)
        inverse_name = getattr(field, 'inverse', False)
        if compute_name and not inverse_name:
            return False
        return True

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

    def _wgs_extract_interval_from_plan(self, plan):
        interval_value = 1
        interval_unit = 'month'
        if not plan:
            return interval_value, interval_unit

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

    def _wgs_extract_plan_record_from_product(self, product):
        product.ensure_one()

        if self._wgs_is_plan_model_name(product._name):
            return product
        if self._wgs_is_plan_model_name(product.product_tmpl_id._name):
            return product.product_tmpl_id

        for source in (product, product.product_tmpl_id):
            for field_name in ('plan_id', 'subscription_plan_id', 'recurring_plan_id'):
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

    def _wgs_extract_plan_record_from_pricing(self, pricing):
        if self._wgs_is_plan_model_name(pricing._name):
            return pricing

        for field_name in ('plan_id', 'subscription_plan_id', 'recurring_plan_id'):
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

    def _wgs_extract_plan_id_from_product(self, product):
        plan = self._wgs_extract_plan_record_from_product(product)
        return plan.id if plan else False

    def _wgs_extract_plan_id_from_pricing(self, pricing):
        plan = self._wgs_extract_plan_record_from_pricing(pricing)
        return plan.id if plan else False

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
            'interval_label': '%s %s' % (interval_value, interval_unit),
            'interval_value': interval_value,
            'interval_unit': interval_unit,
            'price': float(price),
        }

    def _wgs_search_product_pricelist_item_records(self, product):
        model_name = 'product.pricelist.item'
        if model_name not in self.env.registry:
            return []

        pricelist_item_model = self.env[model_name]
        fields_map = pricelist_item_model._fields
        records = pricelist_item_model.browse()

        for field_name, field in fields_map.items():
            if field.type != 'many2one':
                continue
            comodel_name = getattr(field, 'comodel_name', False)
            if comodel_name == 'product.product':
                records |= pricelist_item_model.search([(field_name, '=', product.id)])
            elif comodel_name == 'product.template':
                records |= pricelist_item_model.search([(field_name, '=', product.product_tmpl_id.id)])

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
                'interval_label': '%s %s' % (interval_value, interval_unit),
                'interval_value': interval_value,
                'interval_unit': interval_unit,
                'price': float(price),
            })
        return output

    def _wgs_search_subscription_pricing_records(self, product):
        pricing_model_name = 'sale.subscription.pricing'
        if pricing_model_name not in self.env.registry:
            return []

        pricing_model = self.env[pricing_model_name]
        fields_map = pricing_model._fields
        records = pricing_model.browse()

        for field_name in ('product_id', 'product_variant_id'):
            if field_name in fields_map:
                records |= pricing_model.search([(field_name, '=', product.id)])

        for field_name in ('product_template_id', 'product_tmpl_id'):
            if field_name in fields_map:
                records |= pricing_model.search([(field_name, '=', product.product_tmpl_id.id)])

        for field_name, field in fields_map.items():
            if field.type != 'many2one':
                continue
            comodel_name = getattr(field, 'comodel_name', False)
            if comodel_name == 'product.product':
                records |= pricing_model.search([(field_name, '=', product.id)])
            elif comodel_name == 'product.template':
                records |= pricing_model.search([(field_name, '=', product.product_tmpl_id.id)])

        output = []
        seen = set()
        for pricing in records:
            if pricing.id in seen:
                continue
            seen.add(pricing.id)
            candidate = self._wgs_build_pricing_candidate(pricing)
            if candidate:
                output.append(candidate)
        return output

    def _wgs_get_recurring_pricing_candidates(self, product):
        product.ensure_one()
        candidates = []
        seen_pricing_ids = set()

        for source in (product, product.product_tmpl_id):
            for field_name in ('subscription_pricing_ids', 'recurring_pricing_ids'):
                if field_name not in source._fields:
                    continue
                for pricing in source[field_name]:
                    if pricing.id in seen_pricing_ids:
                        continue
                    candidate = self._wgs_build_pricing_candidate(pricing)
                    if candidate:
                        seen_pricing_ids.add(pricing.id)
                        candidates.append(candidate)

            for field_name, field in source._fields.items():
                if field_name in ('subscription_pricing_ids', 'recurring_pricing_ids'):
                    continue
                if getattr(field, 'comodel_name', False) != 'sale.subscription.pricing':
                    continue
                if field.type not in ('many2one', 'one2many', 'many2many'):
                    continue
                for pricing in source[field_name]:
                    if pricing.id in seen_pricing_ids:
                        continue
                    candidate = self._wgs_build_pricing_candidate(pricing)
                    if candidate:
                        seen_pricing_ids.add(pricing.id)
                        candidates.append(candidate)

        candidates.extend(self._wgs_search_product_pricelist_item_records(product))
        if not candidates:
            candidates.extend(self._wgs_search_subscription_pricing_records(product))

        deduped = []
        seen_rows = set()
        for row in candidates:
            row_key = (
                int(row.get('plan_id') or 0),
                int(row.get('pricing_id') or 0),
                float(row.get('price') or 0.0),
            )
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            deduped.append(row)
        deduped.sort(key=lambda row: (row.get('sequence') or 1000, row.get('pricing_id') or 0, row.get('plan_id') or 0))
        return deduped

    def _wgs_get_recurring_pricing_choice(self, product, fallback=0.0, preferred_plan_id=False, preferred_pricing_id=False):
        product.ensure_one()
        fallback_price = float(fallback or 0.0)
        candidates = self._wgs_get_recurring_pricing_candidates(product)
        if not candidates:
            return {
                'price': fallback_price,
                'plan_id': self._wgs_extract_plan_id_from_product(product) or False,
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
                return matching[0]
        return candidates[0]

    def _wgs_find_plan_record_by_id(self, plan_id):
        if not plan_id:
            return False
        candidate_model_names = set()

        for model_name in ('sale.order', 'sale.order.line', 'product.product', 'product.template', 'sale.subscription.pricing'):
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

    def _wgs_get_plan_min_end_threshold(self, plan, start_date, periods_count=1):
        start_date = fields.Date.to_date(start_date) or fields.Date.context_today(self)
        interval_value, interval_unit = self._wgs_extract_interval_from_plan(plan)
        interval_value = interval_value * max(1, int(periods_count or 1))
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

    def _wgs_find_partner_multi_field(self, sale_order):
        field = sale_order._fields.get('participant_ids')
        if field and field.type in ('many2many', 'one2many') and getattr(field, 'comodel_name', '') == 'res.partner':
            return 'participant_ids'

        for field_name, field in sale_order._fields.items():
            if field.type not in ('many2many', 'one2many'):
                continue
            if getattr(field, 'comodel_name', '') != 'res.partner':
                continue
            normalized_name = (field_name or '').lower()
            if any(token in normalized_name for token in ('participant', 'member', 'attendee')):
                return field_name
        return False

    def _wgs_find_subscription_end_date_field(self, sale_order):
        preferred = ('end_date', 'date_end', 'subscription_end_date', 'recurring_end_date')
        for field_name in preferred:
            field = sale_order._fields.get(field_name)
            if field and field.type in ('date', 'datetime'):
                return field_name
        return False

    def _wgs_find_subscription_start_date_field(self, sale_order):
        preferred = ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date', 'recurring_start_date')
        for field_name in preferred:
            field = sale_order._fields.get(field_name)
            if field and field.type in ('date', 'datetime'):
                return field_name
        return False

    def _wgs_find_subscription_contract_date_field(self, sale_order):
        preferred = ('first_contract_date', 'contract_date', 'date_contract')
        for field_name in preferred:
            field = sale_order._fields.get(field_name)
            if field and field.type in ('date', 'datetime'):
                return field_name
        return False

    def _wgs_find_subscription_next_invoice_date_field(self, sale_order):
        preferred = ('recurring_next_date', 'next_invoice_date', 'recurring_next_invoice_date')
        for field_name in preferred:
            field = sale_order._fields.get(field_name)
            if field and field.type in ('date', 'datetime'):
                return field_name
        return False

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

    def _wgs_get_subscription_orders_from_base(self, sale_order):
        orders = sale_order
        for field_name, field in sale_order._fields.items():
            if getattr(field, 'comodel_name', '') != 'sale.order':
                continue
            normalized_name = (field_name or '').lower()
            if 'subscription' not in normalized_name and 'recurr' not in normalized_name:
                continue
            value = sale_order[field_name]
            if field.type == 'many2one' and value:
                orders |= value
            elif field.type in ('one2many', 'many2many'):
                orders |= value

        recurring_orders = orders.filtered(
            lambda order: bool(order.order_line.filtered(lambda line: self._wgs_is_recurring_so_line(line)))
        )
        return recurring_orders or sale_order

    def _wgs_sync_subscription_metadata(
        self,
        sale_order,
        participant_ids,
        contract_date=False,
        subscription_start_date=False,
        subscription_end_date=False,
        next_billing_date=False,
    ):
        target_orders = self._wgs_get_subscription_orders_from_base(sale_order)
        for target_order in target_orders:
            values = {}
            participant_field = self._wgs_find_partner_multi_field(target_order)
            if participant_field:
                values[participant_field] = [Command.set(participant_ids or [])]
            if contract_date:
                contract_field = self._wgs_find_subscription_contract_date_field(target_order)
                if contract_field:
                    values[contract_field] = self._wgs_convert_date_for_field_value(
                        contract_date,
                        target_order._fields.get(contract_field),
                    )
                elif 'date_order' in target_order._fields:
                    values['date_order'] = self._wgs_convert_date_for_field_value(
                        contract_date,
                        target_order._fields.get('date_order'),
                    )
            if subscription_start_date:
                start_field = self._wgs_find_subscription_start_date_field(target_order)
                if start_field:
                    values[start_field] = self._wgs_convert_date_for_field_value(
                        subscription_start_date,
                        target_order._fields.get(start_field),
                    )
            if subscription_end_date:
                end_field = self._wgs_find_subscription_end_date_field(target_order)
                if end_field:
                    values[end_field] = self._wgs_convert_date_for_field_value(
                        subscription_end_date,
                        target_order._fields.get(end_field),
                    )
            if next_billing_date:
                next_field = self._wgs_find_subscription_next_invoice_date_field(target_order)
                if next_field:
                    values[next_field] = self._wgs_convert_date_for_field_value(
                        next_billing_date,
                        target_order._fields.get(next_field),
                    )
            if values:
                target_order.write(values)

    def _wgs_recompute_stored_field(self, record, field_name):
        field = record._fields.get(field_name)
        compute_name = getattr(field, 'compute', False) if field else False
        if not compute_name:
            return
        method = getattr(record, compute_name, None) if isinstance(compute_name, str) else False
        if not callable(method):
            return
        try:
            method()
        except Exception as error:  # pragma: no cover - runtime-specific behavior
            _logger.warning('WGS import: compute %s failed on %s (%s)', compute_name, record, error)

    def _wgs_call_optional_methods(self, record, method_names):
        for method_name in method_names:
            method = getattr(record, method_name, None)
            if not callable(method):
                continue
            try:
                method()
            except TypeError:
                continue
            except Exception as error:  # pragma: no cover - runtime-specific behavior
                _logger.warning('WGS import: optional method %s failed on %s (%s)', method_name, record, error)

    def _wgs_refresh_native_subscription_markers(self, order):
        order.ensure_one()
        recurring_lines = order.order_line.filtered(lambda line: self._wgs_is_recurring_so_line(line))
        for line in recurring_lines:
            self._wgs_call_optional_methods(
                line,
                (
                    '_onchange_product_id',
                    '_onchange_subscription_plan_id',
                    '_onchange_plan_id',
                    '_onchange_recurring_plan_id',
                ),
            )
            for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
                self._wgs_recompute_stored_field(line, field_name)

        self._wgs_call_optional_methods(
            order,
            (
                '_onchange_order_line',
                '_onchange_subscription_plan_id',
                '_onchange_plan_id',
                '_onchange_recurring_plan_id',
            ),
        )
        for field_name in ('is_subscription', 'plan_id', 'subscription_state', 'recurring_next_date', 'next_invoice_date'):
            self._wgs_recompute_stored_field(order, field_name)

    def _wgs_is_order_natively_subscription(self, order):
        order.ensure_one()
        recurring_lines = order.order_line.filtered(lambda line: self._wgs_is_recurring_so_line(line))
        if not recurring_lines:
            return False

        if 'is_subscription' in order._fields:
            return bool(order.is_subscription)

        if 'plan_id' in order._fields and order.plan_id:
            return True

        for line in recurring_lines:
            for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
                if field_name in line._fields and line[field_name]:
                    return True

        return False
