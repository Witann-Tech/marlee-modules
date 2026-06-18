import logging

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
                return fields.Date.to_date(value)
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
    def _wgs_get_subscription_access_audit_partner_ids(self, batch_limit=5000):
        domain = [('state', 'in', ['sale', 'done'])]
        if 'order_line' in self._fields:
            domain.append(('order_line.product_id.product_tmpl_id.recurring_invoice', '=', True))
        orders = self.sudo().search(domain, order='write_date asc, id asc', limit=int(batch_limit or 5000))
        orders = orders.filtered(lambda order: order._get_subscription_recurring_lines())
        partner_ids = set()
        for order in orders:
            partner_ids.update(order._wgs_get_access_related_partner_ids())

        Person = self.env['access_control.person'].sudo()
        managed_people = Person.search([
            ('managed_by_subscription', '=', True),
            ('partner_id', '!=', False),
        ])
        partner_ids.update(managed_people.mapped('partner_id').ids)
        return sorted(partner_ids), len(orders)

    @api.model
    def _wgs_build_subscription_access_audit_line(self, partner):
        profile = self._wgs_get_access_profile_for_partner(partner)
        Person = self.env['access_control.person'].sudo()
        person = Person.search([('partner_id', '=', partner.id)], limit=1)
        expected_state = profile.get('access_state') or False
        expected_site_ids = set(profile.get('site_ids') or [])
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
                    'current_active': False,
                    'current_state': False,
                    'current_site_ids': [],
                    'order_ids': profile.get('order_ids') or [],
                }
            current_site_ids = set(person.site_ids.ids)
            if (
                not person.active
                or person.access_state != 'enabled'
                or current_site_ids != expected_site_ids
                or not person.managed_by_subscription
            ):
                return {
                    'issue': 'person_mismatch',
                    'partner_id': partner.id,
                    'person_id': person.id,
                    'expected_active': True,
                    'expected_state': expected_state,
                    'expected_site_ids': sorted(expected_site_ids),
                    'current_active': bool(person.active),
                    'current_state': person.access_state or False,
                    'current_site_ids': sorted(current_site_ids),
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
                'current_active': bool(person.active),
                'current_state': person.access_state or False,
                'current_site_ids': sorted(person.site_ids.ids),
                'current_managed_by_subscription': True,
                'order_ids': profile.get('order_ids') or [],
            }
        return False

    @api.model
    def wgs_audit_subscription_access_control(self, repair=False, batch_limit=5000):
        partner_ids, order_count = self._wgs_get_subscription_access_audit_partner_ids(batch_limit=batch_limit)
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

        summary = {
            'checked_partners': len(partners),
            'checked_orders': order_count,
            'issues': len(lines),
            'repaired': len(repaired_partner_ids),
            'repaired_partner_ids': repaired_partner_ids,
            'lines': lines,
        }
        _logger.info(
            'WGS ACCESS: audit repair=%s checked_partners=%s checked_orders=%s issues=%s repaired=%s',
            bool(repair),
            summary['checked_partners'],
            summary['checked_orders'],
            summary['issues'],
            summary['repaired'],
        )
        return summary

    @api.model
    def _cron_wgs_sync_subscription_access_control(self, batch_limit=5000):
        return self.wgs_audit_subscription_access_control(repair=True, batch_limit=batch_limit)

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
