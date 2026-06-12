import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

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

    def _wgs_get_access_site_ids(self):
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

    def _wgs_get_access_timezone(self):
        self.ensure_one()
        if self.wgs_access_timezone_id:
            return self.wgs_access_timezone_id
        for line in self._get_subscription_recurring_lines():
            product_tmpl = line.product_id.product_tmpl_id if line.product_id else False
            if product_tmpl and product_tmpl.wgs_access_timezone_id:
                return product_tmpl.wgs_access_timezone_id
        return self.env.ref('access_control_api.access_timezone_general', raise_if_not_found=False)

    def _wgs_get_first_access_date_value(self, field_names):
        self.ensure_one()
        for field_name in field_names:
            if field_name not in self._fields:
                continue
            value = self[field_name]
            if value:
                return fields.Date.to_date(value)
        return False

    def _wgs_classify_subscription_access_state(self):
        self.ensure_one()
        if not self._get_subscription_recurring_lines():
            return False
        if 'subscription_state' not in self._fields:
            return False

        state_value = (self.subscription_state or '').strip().lower()
        if not state_value:
            return False
        if any(token in state_value for token in self._WGS_ACCESS_SUSPENDED_STATE_TOKENS):
            return 'suspended'
        if any(token in state_value for token in self._WGS_ACCESS_DISABLED_STATE_TOKENS):
            return False
        if not any(token in state_value for token in self._WGS_ACCESS_ENABLED_STATE_TOKENS):
            return False

        today = fields.Date.context_today(self)
        if self._wgs_get_optional_field_value('wgs_direct_debit_subscription'):
            return self._wgs_classify_direct_debit_access_state(today)

        start_date = self._wgs_get_first_access_date_value(
            ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date', 'date_order')
        )
        if start_date and start_date > today:
            return False

        next_invoice_date = self._wgs_get_first_access_date_value(
            ('recurring_next_date', 'next_invoice_date', 'recurring_next_invoice_date')
        )
        if next_invoice_date and next_invoice_date <= today:
            return False

        hard_end_date = self._wgs_get_first_access_date_value(
            ('date_end', 'end_date', 'subscription_end_date', 'recurring_end_date')
        )
        if hard_end_date and hard_end_date < today:
            return False

        return 'enabled'

    def _wgs_get_optional_field_value(self, field_name, default=False):
        self.ensure_one()
        return self[field_name] if field_name in self._fields else default

    def _wgs_classify_direct_debit_access_state(self, today):
        self.ensure_one()
        today = fields.Date.to_date(today) or fields.Date.context_today(self)

        start_date = self._wgs_get_optional_field_value('wgs_direct_debit_term_start_date') or self._wgs_get_first_access_date_value(
            ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date', 'date_order')
        )
        if start_date and start_date > today:
            return False

        term_end = self._wgs_get_optional_field_value('wgs_direct_debit_term_end_date') or self._wgs_get_first_access_date_value(
            ('date_end', 'end_date', 'subscription_end_date', 'recurring_end_date')
        )
        if term_end and term_end < today:
            return False

        paid_until = self._wgs_get_optional_field_value('wgs_direct_debit_paid_until_date')
        current_month_end = today + relativedelta(day=31)
        if paid_until and paid_until >= current_month_end:
            return 'enabled'

        last_start = self._wgs_get_optional_field_value('wgs_direct_debit_last_month_start_date')
        last_end = self._wgs_get_optional_field_value('wgs_direct_debit_last_month_end_date') or term_end
        if last_start and last_end and last_start <= today <= last_end:
            previous_month_end = last_start - relativedelta(days=1)
            if not paid_until or paid_until < previous_month_end:
                return False
            return 'enabled'

        return False

    @api.model
    def _wgs_get_related_subscription_orders_for_partner(self, partner):
        if not partner:
            return self.browse()
        orders = self.sudo().search(
            ['|', ('partner_id', '=', partner.id), ('participant_ids', 'in', partner.id)],
            order='id asc',
        )
        return orders.filtered(lambda order: order._get_subscription_recurring_lines())

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
        site_ids = set()
        access_timezone = False
        considered_orders = []
        for order in orders:
            state = order._wgs_classify_subscription_access_state()
            if not state:
                continue
            considered_orders.append(order.id)
            site_ids.update(order._wgs_get_access_site_ids())
            order_timezone = order._wgs_get_access_timezone()
            if order_timezone and (not access_timezone or order_timezone.timezone_id > 1):
                access_timezone = order_timezone
            if state == 'enabled':
                enabled = True
            elif state == 'suspended':
                suspended = True

        profile['site_ids'] = sorted(site_ids)
        profile['order_ids'] = considered_orders
        profile['access_timezone_id'] = access_timezone.id if access_timezone else False
        if enabled:
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

    @api.model
    def _cron_wgs_sync_subscription_access_control(self, batch_limit=5000):
        domain = [('state', 'in', ['sale', 'done'])]
        if 'order_line' in self._fields:
            domain.append(('order_line.product_id.product_tmpl_id.recurring_invoice', '=', True))
        orders = self.sudo().search(domain, order='write_date asc, id asc', limit=int(batch_limit or 5000))
        orders = orders.filtered(lambda order: order._get_subscription_recurring_lines())
        partner_ids = set()
        for order in orders:
            partner_ids.update(order._wgs_get_access_related_partner_ids())
        if partner_ids:
            self.browse()._wgs_sync_access_control_people(extra_partner_ids=partner_ids)
        _logger.info(
            'WGS ACCESS: cron resynced subscription access orders=%s partners=%s',
            len(orders),
            len(partner_ids),
        )
        return True

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._ensure_subscription_owner_is_participant()
        orders._wgs_sync_access_control_people()
        return orders

    def write(self, vals):
        before_partner_ids = self._wgs_get_access_related_partner_ids()
        res = super().write(vals)
        if not self.env.context.get('skip_owner_participant_sync'):
            self._ensure_subscription_owner_is_participant()
        sync_orders = self.with_context(access_sync_priority=True) if 'wgs_access_timezone_id' in vals else self
        sync_orders._wgs_sync_access_control_people(extra_partner_ids=before_partner_ids)
        return res

    def unlink(self):
        impacted_partner_ids = self._wgs_get_access_related_partner_ids()
        res = super().unlink()
        if impacted_partner_ids:
            self._wgs_sync_access_control_people(extra_partner_ids=impacted_partner_ids)
        return res

    def action_confirm(self):
        res = super().action_confirm()
        self._wgs_sync_access_control_people()
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._wgs_sync_access_control_people()
        return res

    def action_close(self):
        super_method = getattr(super(), 'action_close', None)
        if not super_method:
            return False
        res = super_method()
        self._wgs_sync_access_control_people()
        return res

    def action_subscription_close(self):
        super_method = getattr(super(), 'action_subscription_close', None)
        if not super_method:
            return False
        res = super_method()
        self._wgs_sync_access_control_people()
        return res
