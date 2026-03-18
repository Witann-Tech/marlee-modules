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
    _WGS_POS_SUBSCRIPTION_STATE_PRIORITY = {
        'progress': 0,
        'renew': 1,
        'paused': 2,
        'draft': 3,
        'cancel': 4,
        'closed': 5,
        'upsell': 6,
        'other': 7,
        'none': 8,
    }
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
    def get_partner_subscription_detail_for_pos(self, partner_id):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('No tienes permisos para consultar suscripciones desde Punto de Venta.'))

        partner = self.env['res.partner'].sudo().with_context(active_test=False).browse(int(partner_id or 0)).exists()
        if not partner:
            return {'partner_id': False, 'items': []}

        today = fields.Date.context_today(self)
        subscriptions = self._get_pos_subscription_orders(partner)
        items = []
        for subscription in subscriptions:
            try:
                item = subscription._build_pos_subscription_status_item(today)
            except Exception as error:
                _logger.warning(
                    'WGS POS: could not build subscription detail item (so=%s, partner=%s, error=%s)',
                    subscription.id,
                    partner.id,
                    error,
                )
                item = False
            if item:
                item['is_owner'] = bool(subscription.partner_id and subscription.partner_id.id == partner.id)
                item['partner_role_label'] = _('Titular') if item['is_owner'] else _('Participante')
                item['participant_ids'] = subscription.participant_ids.ids
                item['participant_names'] = subscription.participant_ids.mapped('display_name')
                item['participant_count'] = len(subscription.participant_ids)
                item['max_participants_total'] = int(
                    getattr(subscription, 'subscription_max_participants_total', 0) or item['participant_count'] or 1
                )
                items.append(item)

        items = sorted(items, key=self._sort_subscription_status_item_key_for_pos)
        status_map = self.get_partner_subscription_status_map_for_pos([partner.id])
        summary = status_map.get(partner.id, {})

        birthday_value = summary.get('birthday') or self._get_partner_field_value_for_pos(
            partner, self._PARTNER_BIRTHDAY_FIELD_CANDIDATES
        )
        gender_value = summary.get('gender') or self._get_partner_field_value_for_pos(
            partner, self._PARTNER_GENDER_FIELD_CANDIDATES
        )
        last_access_value = summary.get('last_access') or self._get_partner_field_value_for_pos(
            partner, self._PARTNER_LAST_ACCESS_FIELD_CANDIDATES
        )
        phone_value = summary.get('phone') or self._get_partner_field_value_for_pos(partner, ('phone', 'mobile'))
        email_value = summary.get('email') or self._get_partner_field_value_for_pos(partner, ('email',))

        return {
            'partner_id': partner.id,
            'partner_name': partner.display_name,
            'state': summary.get('state') or 'none',
            'state_label': summary.get('state_label') or _('Sin suscripción'),
            'package_label': summary.get('package_label') or False,
            'plan_name': summary.get('plan_name') or False,
            'start_date': summary.get('start_date') or False,
            'valid_until': summary.get('valid_until') or False,
            'phone': phone_value or False,
            'email': email_value or False,
            'gender': gender_value or False,
            'birthday': birthday_value or False,
            'last_access': last_access_value or False,
            'image_url': summary.get('image_url') or ('/web/image/res.partner/%s/image_128' % partner.id),
            'items': items,
        }

    @api.model
    def wgs_update_subscription_participants_for_pos(self, subscription_id, participant_ids):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('No tienes permisos para actualizar participantes desde Punto de Venta.'))

        subscription = self.sudo().browse(int(subscription_id or 0)).exists()
        if not subscription:
            raise AccessError(_('La suscripción seleccionada no existe.'))
        if not subscription._is_subscription_record_for_pos():
            raise AccessError(_('La orden seleccionada no corresponde a una suscripción válida.'))
        if 'participant_ids' not in subscription._fields:
            raise AccessError(_('La suscripción no expone participantes editables en este entorno.'))

        cleaned_ids = []
        for value in participant_ids or []:
            try:
                participant_id = int(value)
            except (TypeError, ValueError):
                continue
            if participant_id > 0:
                cleaned_ids.append(participant_id)
        cleaned_ids = list(dict.fromkeys(cleaned_ids))

        owner_id = subscription.partner_id.id if subscription.partner_id else False
        if owner_id and owner_id not in cleaned_ids:
            cleaned_ids.insert(0, owner_id)

        participants = self.env['res.partner'].sudo().with_context(active_test=False).browse(cleaned_ids).exists()
        subscription.write({'participant_ids': [fields.Command.set(participants.ids)]})
        subscription._ensure_subscription_owner_is_participant()

        return {
            'ok': True,
            'subscription_id': subscription.id,
            'participant_ids': subscription.participant_ids.ids,
            'participant_names': subscription.participant_ids.mapped('display_name'),
            'participant_count': len(subscription.participant_ids),
            'max_participants_total': int(getattr(subscription, 'subscription_max_participants_total', 0) or 0),
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
                'state_label': summary.get('state_label') or _('Sin suscripción'),
                'short_label': summary.get('short_label') or False,
                'valid_until': summary.get('valid_until') or False,
                'start_date': summary.get('start_date') or False,
                'subscription_id': summary.get('subscription_id') or False,
                'package_label': summary.get('package_label') or False,
                'package_names': summary.get('package_names') or [],
                'plan_name': summary.get('plan_name') or False,
                'reason': summary.get('reason') or False,
                'subscription_name': summary.get('subscription_name') or False,
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
                'state_label': status.get('state_label') or _('Sin suscripción'),
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
                'state_label': _('Sin suscripción'),
                'short_label': False,
                'valid_until': False,
                'start_date': False,
                'subscription_id': False,
                'package_label': False,
                'package_names': [],
                'plan_name': False,
                'reason': False,
                'subscription_name': False,
            }

        prioritized = sorted(items, key=self._sort_subscription_status_item_key_for_pos)
        primary = prioritized[0]
        state = primary.get('native_state_key') or 'other'
        state_label = primary.get('native_state_label') or _('Sin suscripción')
        short_label = '[%s]' % state_label.upper()

        access_enabled_items = [row for row in items if row.get('access_state') == 'enabled']
        package_source_items = access_enabled_items or prioritized[:1]

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
            'state_label': state_label,
            'short_label': short_label,
            'valid_until': primary.get('valid_until') or False,
            'start_date': primary.get('start_date') or primary.get('period_start') or False,
            'subscription_id': primary.get('subscription_id') or False,
            'package_label': package_label,
            'package_names': package_names,
            'plan_name': primary.get('plan_name') or False,
            'reason': primary.get('reason') or False,
            'subscription_name': primary.get('subscription_name') or False,
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
        primary_recurring_line = recurring_lines.sorted(key=lambda line: line.id)[:1]
        renewal_product = primary_recurring_line.product_id if primary_recurring_line else self.env['product.product']
        renewal_plan_id = False
        renewal_pricing_id = False
        if primary_recurring_line:
            for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
                if field_name in primary_recurring_line._fields and primary_recurring_line[field_name]:
                    renewal_plan_id = primary_recurring_line[field_name].id
                    break
            for field_name in ('subscription_pricing_id', 'pricing_id', 'recurring_pricing_id'):
                if field_name in primary_recurring_line._fields and primary_recurring_line[field_name]:
                    renewal_pricing_id = primary_recurring_line[field_name].id
                    break

        is_valid = False
        reason = _('La suscripción no está vigente para control de acceso.')
        plan_name = self._get_subscription_plan_name_for_pos(recurring_lines)
        access_state = self._classify_subscription_access_state_for_pos()
        native_state_key, native_state_label = self._get_native_subscription_state_info_for_pos()

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

        if hard_end_date and hard_end_date < today:
            access_state = False
            is_valid = False
            reason = _('La suscripción ya terminó y no debe contarse como vigente.')
        elif start_date and start_date > today:
            access_state = False
            is_valid = False
            reason = _('La suscripción todavía no inicia.')
        if access_state == 'enabled':
            is_valid = True
            reason = _('Suscripción en progreso o en renovación.')
        elif access_state == 'suspended':
            reason = _('La suscripción está pausada o suspendida.')
        else:
            reason = _('La suscripción no está en progreso ni en renovación.')

        pending_documents = []
        for move in self._wgs_get_pending_invoice_records_for_pos():
            amount_total = float(getattr(move, 'amount_total', 0.0) or 0.0)
            amount_residual = float(getattr(move, 'amount_residual', 0.0) or 0.0)
            pending_documents.append({
                'document_model': move._name,
                'document_id': move.id,
                'name': move.name or move.display_name or False,
                'invoice_date': fields.Date.to_string(move.invoice_date) if getattr(move, 'invoice_date', False) else False,
                'invoice_date_due': fields.Date.to_string(move.invoice_date_due) if getattr(move, 'invoice_date_due', False) else False,
                'amount_total': round(max(amount_total, 0.0), 2),
                'amount_residual': round(max(amount_residual, 0.0), 2),
                'currency_symbol': move.currency_id.symbol if getattr(move, 'currency_id', False) else False,
                'payment_state': getattr(move, 'payment_state', False) or False,
                'state': getattr(move, 'state', False) or False,
            })
        first_pending = pending_documents[:1]

        return {
            'subscription_id': self.id,
            'subscription_name': self.name,
            'state': self.subscription_state if 'subscription_state' in self._fields else False,
            'access_state': access_state or False,
            'native_state_key': native_state_key,
            'native_state_label': native_state_label,
            'holder_partner_id': self.partner_id.id or False,
            'holder_partner_name': self.partner_id.display_name or False,
            'package_names': sorted(set(recurring_lines.mapped('product_id.display_name'))),
            'plan_name': plan_name,
            'renewal_product_id': renewal_product.id or False,
            'renewal_product_name': renewal_product.display_name or False,
            'renewal_plan_id': renewal_plan_id,
            'renewal_pricing_id': renewal_pricing_id,
            'start_date': start_date.isoformat() if start_date else False,
            'period_start': period_start.isoformat() if period_start else False,
            'valid_until': valid_until.isoformat() if valid_until else False,
            'next_invoice_date': next_invoice_date.isoformat() if next_invoice_date else False,
            'is_valid': is_valid,
            'status_label': _('Vigente') if is_valid else _('Sin vigencia'),
            'reason': reason,
            'pending_documents': pending_documents,
            'pending_document_count': len(pending_documents),
            'has_pending_document': bool(pending_documents),
            'pending_amount_total': first_pending[0]['amount_residual'] if first_pending else 0.0,
            'pending_document_name': first_pending[0]['name'] if first_pending else False,
        }

    def _wgs_get_pending_invoice_records_for_pos(self):
        self.ensure_one()
        account_move_model = self.env['account.move'].sudo()
        moves = account_move_model.browse()

        if 'invoice_ids' in self._fields:
            moves |= self.invoice_ids.sudo()

        if not moves and self.name and 'invoice_origin' in account_move_model._fields:
            search_domain = [
                ('move_type', 'in', ('out_invoice', 'out_receipt')),
                ('state', '=', 'posted'),
                ('invoice_origin', '=', self.name),
            ]
            if self.partner_id and 'partner_id' in account_move_model._fields:
                search_domain.append(('partner_id', '=', self.partner_id.id))
            moves |= account_move_model.search(search_domain, order='invoice_date_due asc, invoice_date asc, id asc')

        if not moves and self.partner_id:
            fallback_domain = [
                ('move_type', 'in', ('out_invoice', 'out_receipt')),
                ('state', '=', 'posted'),
                ('partner_id', '=', self.partner_id.id),
                ('payment_state', 'not in', ('paid', 'in_payment', 'reversed')),
            ]
            if 'invoice_origin' in account_move_model._fields and self.name:
                fallback_domain.append(('invoice_origin', 'ilike', self.name))
            moves |= account_move_model.search(fallback_domain, order='invoice_date_due asc, invoice_date asc, id asc')

        moves = moves.filtered(
            lambda move: (
                getattr(move, 'move_type', False) in ('out_invoice', 'out_receipt')
                and getattr(move, 'state', False) == 'posted'
                and float(getattr(move, 'amount_residual', 0.0) or 0.0) > 0.00001
                and getattr(move, 'payment_state', False) not in ('paid', 'in_payment', 'reversed')
            )
        )
        return moves.sorted(key=lambda move: (
            fields.Date.to_string(getattr(move, 'invoice_date_due', False) or getattr(move, 'invoice_date', False) or date.max),
            move.id,
        ))

    def _sort_subscription_status_item_key_for_pos(self, row):
        state_rank = self._WGS_POS_SUBSCRIPTION_STATE_PRIORITY.get(
            row.get('native_state_key') or 'other',
            self._WGS_POS_SUBSCRIPTION_STATE_PRIORITY['other'],
        )
        return (
            state_rank,
            row.get('valid_until') or '9999-12-31',
            row.get('start_date') or row.get('period_start') or '9999-12-31',
            row.get('subscription_name') or '',
        )

    def _get_recurring_lines(self):
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: line.product_id and line.product_id.product_tmpl_id.recurring_invoice
        )

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

    def _classify_subscription_access_state_for_pos(self):
        self.ensure_one()
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

    def _get_native_subscription_state_info_for_pos(self):
        self.ensure_one()
        display_label = self._get_subscription_state_display_for_pos()
        state_value = (self.subscription_state or '').strip().lower() if 'subscription_state' in self._fields else ''
        haystack = ' '.join(filter(None, [state_value, (display_label or '').strip().lower()]))

        if not haystack:
            return 'other', _('Sin estado')
        if any(token in haystack for token in ('progress', 'in progress', 'in_progress', 'en progreso')):
            return 'progress', display_label or _('En progreso')
        if any(token in haystack for token in ('renew', 'to renew', 'por renovar')):
            return 'renew', display_label or _('Por renovar')
        if any(token in haystack for token in self._WGS_ACCESS_SUSPENDED_STATE_TOKENS):
            return 'paused', display_label or _('Pausada')
        if any(token in haystack for token in ('draft', 'borrador')):
            return 'draft', display_label or _('Borrador')
        if any(token in haystack for token in ('cancel', 'cancelled', 'canceled', 'cancelada')):
            return 'cancel', display_label or _('Cancelada')
        if any(token in haystack for token in ('close', 'closed', 'cerrada')):
            return 'closed', display_label or _('Cerrada')
        if 'upsell' in haystack:
            return 'upsell', display_label or _('Upsell')
        return 'other', display_label or (self.subscription_state if 'subscription_state' in self._fields else _('Sin estado'))

    def _get_subscription_state_display_for_pos(self):
        self.ensure_one()
        field = self._fields.get('subscription_state')
        if not field:
            return False
        return self._format_value_for_pos(self.subscription_state, field)

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
