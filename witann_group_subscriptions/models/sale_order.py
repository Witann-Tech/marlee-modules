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
        'renew',
        'to renew',
        'por renovar',
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
        company_ids = self._wgs_get_access_product_company_ids()
        if not company_ids:
            return []
        Site = self.env['access_control.site'].sudo()
        return Site.search(
            [('active', '=', True), ('company_id', 'in', company_ids)],
            order='id asc',
        ).ids

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
        if any(token in state_value for token in self._WGS_ACCESS_ENABLED_STATE_TOKENS):
            return 'enabled'
        if any(token in state_value for token in self._WGS_ACCESS_DISABLED_STATE_TOKENS):
            return False
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
        }
        orders = self._wgs_get_related_subscription_orders_for_partner(partner)
        if not orders:
            return profile

        enabled = False
        suspended = False
        site_ids = set()
        considered_orders = []
        for order in orders:
            state = order._wgs_classify_subscription_access_state()
            if not state:
                continue
            considered_orders.append(order.id)
            site_ids.update(order._wgs_get_access_site_ids())
            if state == 'enabled':
                enabled = True
            elif state == 'suspended':
                suspended = True

        profile['site_ids'] = sorted(site_ids)
        profile['order_ids'] = considered_orders
        if enabled:
            profile['access_state'] = 'enabled'
        elif suspended:
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

        if access_state and not site_ids:
            _logger.warning(
                'WGS ACCESS: no se encontraron sitios para partner=%s order_ids=%s; acceso desactivado por seguridad',
                partner.id,
                profile['order_ids'],
            )
            if person:
                vals = {
                    'managed_by_subscription': True,
                    'access_state': 'enabled',
                }
                if person.active:
                    vals['active'] = False
                person.write(vals)
            return False

        if access_state:
            vals = {
                'partner_id': partner.id,
                'active': True,
                'access_state': access_state,
                'site_ids': [Command.set(site_ids)],
                'managed_by_subscription': True,
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
                'access_state': 'enabled',
            }
            if person.active:
                vals['active'] = False
            if person.active or person.access_state != 'enabled' or not person.managed_by_subscription:
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
        self._wgs_sync_access_control_people(extra_partner_ids=before_partner_ids)
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
