import json
import logging
from datetime import date, datetime, time, timedelta

import pytz
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'
    _WGS_POS_ACCESS_RESYNC_COOLDOWN_SECONDS = 60
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
    _WGS_POS_DIRECTORY_STATE_ALIASES = {
        'actionable': ('progress', 'renew'),
        'cancel': ('cancel', 'closed'),
    }
    _PARTNER_GENDER_FIELD_CANDIDATES = (
        'gender',
        'x_gender',
        'x_studio_gender',
        'x_studio_genero',
    )
    _PARTNER_BIRTHDAY_FIELD_CANDIDATES = (
        'x_studio_fecha_de_nacimiento',
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
    _PARTNER_CURP_FIELD_CANDIDATES = (
        'x_studio_curp',
    )

    @api.model
    def _wgs_ensure_pos_user_for_pos(self, error_message):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(error_message)

    @api.model
    def _wgs_partner_model_for_pos(self):
        return self.env['res.partner'].sudo().with_context(active_test=False)

    @api.model
    def _wgs_person_model_for_pos(self):
        return self.env['access_control.person'].sudo()

    @api.model
    def _wgs_account_move_model_for_pos(self):
        return self.env['account.move'].sudo()

    @api.model
    def _wgs_browse_partner_for_pos(self, partner_id):
        try:
            partner_id = int(partner_id or 0)
        except (TypeError, ValueError):
            partner_id = 0
        if partner_id <= 0:
            return self.env['res.partner']
        return self._wgs_partner_model_for_pos().browse(partner_id).exists()

    @api.model
    def _wgs_browse_subscription_for_pos(self, subscription_id):
        try:
            subscription_id = int(subscription_id or 0)
        except (TypeError, ValueError):
            subscription_id = 0
        if subscription_id <= 0:
            return self.browse()
        return self.sudo().browse(subscription_id).exists()

    @api.model
    def _wgs_raise_pos_data_error(self, message, *, error=False, **context):
        if error:
            _logger.warning('WGS POS data error: %s | context=%s | error=%s', message, context, error)
        else:
            _logger.warning('WGS POS data error: %s | context=%s', message, context)
        raise AccessError(message)

    @api.model
    def _wgs_and_domains_for_pos(self, left_domain, right_domain):
        left_domain = list(left_domain or [])
        right_domain = list(right_domain or [])
        if not left_domain:
            return right_domain
        if not right_domain:
            return left_domain
        return ['&', *left_domain, *right_domain]

    @api.model
    def _wgs_or_leaves_for_pos(self, leaves):
        leaves = [leaf for leaf in (leaves or []) if leaf]
        if not leaves:
            return []
        if len(leaves) == 1:
            return [leaves[0]]
        return ['|'] * (len(leaves) - 1) + leaves

    @api.model
    def get_partner_subscription_status_for_pos(self, partner_id):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar vigencia desde Punto de Venta.'))

        partner = self._wgs_browse_partner_for_pos(partner_id)
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
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar suscripciones desde Punto de Venta.'))

        partner = self._wgs_browse_partner_for_pos(partner_id)
        if not partner:
            return {'partner_id': False, 'items': []}

        today = fields.Date.context_today(self)
        subscriptions = self._get_pos_subscription_orders(partner)
        items = []
        for subscription in subscriptions:
            try:
                item = subscription._build_pos_subscription_status_item(today)
            except Exception as error:
                self._wgs_raise_pos_data_error(
                    _('No se pudo construir el detalle de suscripciones para este cliente.'),
                    error=error,
                    subscription_id=subscription.id,
                    partner_id=partner.id,
                )
            if item and self._should_display_subscription_item_in_pos_detail(item, today=today):
                item['is_owner'] = bool(subscription.partner_id and subscription.partner_id.id == partner.id)
                item['partner_role_label'] = _('Titular') if item['is_owner'] else _('Participante')
                item['participant_ids'] = subscription.participant_ids.ids
                item['participant_names'] = subscription.participant_ids.mapped('display_name')
                item['participant_count'] = len(subscription.participant_ids)
                item['max_participants_total'] = int(
                    getattr(subscription, 'subscription_max_participants_total', 0) or item['participant_count'] or 1
                )
                item['access_people_summary'] = subscription._wgs_get_access_people_summary_for_pos()
                item['_wgs_creation_sort_key'] = self._get_subscription_detail_creation_sort_key_for_pos(subscription)
                items.append(item)

        items = self._filter_partner_subscription_detail_items_for_pos(items)
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
        curp_value = self._get_partner_curp_for_pos(partner)

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
            'curp': curp_value or False,
            'gender': gender_value or False,
            'birthday': birthday_value or False,
            'last_access': last_access_value or False,
            'image_url': summary.get('image_url') or ('/web/image/res.partner/%s/image_128' % partner.id),
            'items': items,
        }

    @api.model
    def wgs_update_subscription_participants_for_pos(self, subscription_id, participant_ids):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para actualizar participantes desde Punto de Venta.'))

        subscription = self._wgs_browse_subscription_for_pos(subscription_id)
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

        participants = self._wgs_partner_model_for_pos().browse(cleaned_ids).exists()
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
    def wgs_create_partner_for_pos(self, vals):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para crear clientes desde Punto de Venta.'))

        values = dict(vals or {})
        name = (values.get('name') or '').strip()
        if not name:
            raise AccessError(_('Debes capturar el nombre del cliente.'))

        Partner = self._wgs_partner_model_for_pos()
        create_vals = {
            'name': name,
            'company_type': 'person',
            'type': 'contact',
        }

        phone = (values.get('phone') or '').strip()
        email = (values.get('email') or '').strip()
        curp = values.get('curp') or False
        image_1920 = values.get('image_1920') or False
        birthday = values.get('birthday') or False
        gender = values.get('gender') or False

        if curp:
            curp_validation = self._wgs_validate_partner_curp_for_pos(curp)
            if not curp_validation.get('ok'):
                return {
                    'ok': False,
                    'error_message': curp_validation.get('message') or _('No se pudo validar la CURP del cliente.'),
                }
            curp = curp_validation.get('normalized') or curp

        if 'phone' in Partner._fields and phone:
            create_vals['phone'] = phone
        if 'mobile' in Partner._fields and phone:
            create_vals['mobile'] = phone
        if 'email' in Partner._fields and email:
            create_vals['email'] = email
        if 'image_1920' in Partner._fields and image_1920:
            create_vals['image_1920'] = image_1920

        self._assign_partner_field_for_pos(Partner, create_vals, self._PARTNER_BIRTHDAY_FIELD_CANDIDATES, birthday)
        self._assign_partner_field_for_pos(Partner, create_vals, self._PARTNER_GENDER_FIELD_CANDIDATES, gender)
        self._assign_partner_field_for_pos(Partner, create_vals, self._PARTNER_CURP_FIELD_CANDIDATES, curp)

        try:
            partner = Partner.create(create_vals)
        except ValidationError as error:
            return {
                'ok': False,
                'error_message': str(error),
            }

        return {
            'ok': True,
            'partner_id': partner.id,
            'partner_name': partner.display_name,
            'phone': self._get_partner_field_value_for_pos(partner, ('phone', 'mobile')) or False,
            'email': self._get_partner_field_value_for_pos(partner, ('email',)) or False,
            'curp': self._get_partner_curp_for_pos(partner) or False,
            'gender': self._get_partner_field_value_for_pos(partner, self._PARTNER_GENDER_FIELD_CANDIDATES) or False,
            'birthday': self._get_partner_field_value_for_pos(partner, self._PARTNER_BIRTHDAY_FIELD_CANDIDATES) or False,
            'image_url': '/web/image/res.partner/%s/image_128' % partner.id,
        }

    @api.model
    def wgs_update_partner_curp_for_pos(self, partner_id, curp):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para actualizar la CURP desde Punto de Venta.'))

        partner = self._wgs_browse_partner_for_pos(partner_id)
        if not partner:
            raise AccessError(_('El cliente seleccionado no existe.'))

        curp_validation = self._wgs_validate_partner_curp_for_pos(curp, exclude_partner=partner)
        if not curp_validation.get('ok'):
            return {
                'ok': False,
                'error_message': curp_validation.get('message') or _('No se pudo validar la CURP del cliente.'),
            }

        write_vals = {}
        field_name = self._assign_partner_field_for_pos(
            partner,
            write_vals,
            self._PARTNER_CURP_FIELD_CANDIDATES,
            curp_validation.get('normalized') or curp,
        )
        if not field_name:
            raise AccessError(_('Este entorno no permite capturar CURP desde Punto de Venta.'))

        try:
            partner.write(write_vals)
        except ValidationError as error:
            return {
                'ok': False,
                'error_message': str(error),
            }
        return {
            'ok': True,
            'partner_id': partner.id,
            'curp': self._get_partner_curp_for_pos(partner) or False,
        }

    @api.model
    def wgs_update_partner_for_pos(self, partner_id, vals):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para actualizar clientes desde Punto de Venta.'))

        partner = self._wgs_browse_partner_for_pos(partner_id)
        if not partner:
            raise AccessError(_('El cliente seleccionado no existe.'))

        values = dict(vals or {})
        name = (values.get('name') or '').strip()
        if not name:
            return {
                'ok': False,
                'error_message': _('Debes capturar el nombre del cliente.'),
            }

        phone = (values.get('phone') or '').strip()
        email = (values.get('email') or '').strip()
        curp = values.get('curp') or False
        birthday = values.get('birthday') or False
        gender = values.get('gender') or False

        if curp:
            curp_validation = self._wgs_validate_partner_curp_for_pos(curp, exclude_partner=partner)
            if not curp_validation.get('ok'):
                return {
                    'ok': False,
                    'error_message': curp_validation.get('message') or _('No se pudo validar la CURP del cliente.'),
                }
            curp = curp_validation.get('normalized') or curp

        write_vals = {'name': name}

        if 'phone' in partner._fields:
            write_vals['phone'] = phone or False
        if 'mobile' in partner._fields:
            write_vals['mobile'] = phone or False
        if 'email' in partner._fields:
            write_vals['email'] = email or False

        self._assign_or_clear_partner_field_for_pos(partner, write_vals, self._PARTNER_BIRTHDAY_FIELD_CANDIDATES, birthday)
        self._assign_or_clear_partner_field_for_pos(partner, write_vals, self._PARTNER_GENDER_FIELD_CANDIDATES, gender)
        field_name = self._assign_or_clear_partner_field_for_pos(partner, write_vals, self._PARTNER_CURP_FIELD_CANDIDATES, curp)
        if not curp and not field_name and any(partner._fields.get(field) for field in self._PARTNER_CURP_FIELD_CANDIDATES):
            for field in self._PARTNER_CURP_FIELD_CANDIDATES:
                if partner._fields.get(field):
                    write_vals[field] = False
                    break

        try:
            partner.write(write_vals)
        except ValidationError as error:
            return {
                'ok': False,
                'error_message': str(error),
            }

        return {
            'ok': True,
            'partner_id': partner.id,
            'partner_name': partner.display_name,
            'phone': self._get_partner_field_value_for_pos(partner, ('phone', 'mobile')) or False,
            'email': self._get_partner_field_value_for_pos(partner, ('email',)) or False,
            'curp': self._get_partner_curp_for_pos(partner) or False,
            'gender': self._get_partner_field_value_for_pos(partner, self._PARTNER_GENDER_FIELD_CANDIDATES) or False,
            'birthday': self._get_partner_field_value_for_pos(partner, self._PARTNER_BIRTHDAY_FIELD_CANDIDATES) or False,
            'image_url': '/web/image/res.partner/%s/image_128' % partner.id,
        }

    @api.model
    def wgs_update_partner_photo_for_pos(self, partner_id, image_1920):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para actualizar la foto desde Punto de Venta.'))

        partner = self._wgs_browse_partner_for_pos(partner_id)
        if not partner:
            raise AccessError(_('El cliente seleccionado no existe.'))
        if 'image_1920' not in partner._fields:
            raise AccessError(_('Este entorno no permite actualizar fotos de clientes.'))

        partner.write({'image_1920': image_1920 or False})
        return {
            'ok': True,
            'partner_id': partner.id,
            'image_url': '/web/image/res.partner/%s/image_128?unique=%s' % (partner.id, fields.Datetime.now().timestamp()),
        }

    @api.model
    def _wgs_access_log_timezone_for_pos(self, timezone_name=False):
        tz_name = (
            timezone_name
            or self.env['ir.config_parameter'].sudo().get_param('access_control.event_timezone')
            or self.env['ir.config_parameter'].sudo().get_param('access_control_api.event_timezone')
            or self.env.user.tz
            or 'America/Mexico_City'
        )
        try:
            return pytz.timezone(tz_name)
        except Exception:
            _logger.warning('WGS POS access log invalid timezone=%s; falling back to America/Mexico_City', tz_name)
            return pytz.timezone('America/Mexico_City')

    @api.model
    def _wgs_parse_access_log_datetime_for_pos(self, value, fallback, timezone_name=False):
        if not value:
            parsed = fallback
        else:
            try:
                parsed = date_parser.parse(str(value))
            except Exception:
                parsed = fallback
        if not parsed:
            return fallback
        if getattr(parsed, 'tzinfo', None):
            return parsed.astimezone(pytz.UTC).replace(tzinfo=None)
        if timezone_name:
            return self._wgs_access_log_timezone_for_pos(timezone_name).localize(parsed).astimezone(pytz.UTC).replace(tzinfo=None)
        return parsed

    @api.model
    def _wgs_access_log_default_local_range_for_pos(self, timezone_name=False):
        tz = self._wgs_access_log_timezone_for_pos(timezone_name)
        today = datetime.now(tz).date()
        return (
            datetime.combine(today, time.min),
            datetime.combine(today + timedelta(days=1), time.min),
        )

    @api.model
    def _wgs_access_log_datetime_to_utc_iso_for_pos(self, value):
        if not value:
            return False
        parsed = fields.Datetime.to_datetime(value)
        if not parsed:
            return False
        return fields.Datetime.to_string(parsed).replace(' ', 'T') + 'Z'

    @api.model
    def _wgs_get_pos_access_sites_for_pos(self, company):
        Site = self.env['access_control.site'].sudo()
        if not company:
            return Site.browse()
        return Site.search([
            ('active', '=', True),
            ('company_id', '=', company.id),
        ], order='name asc, id asc')

    @api.model
    def wgs_open_access_door_for_pos(self, device_id, options=False):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para abrir puertas desde Punto de Venta.'))

        try:
            device_id = int(device_id or 0)
        except (TypeError, ValueError):
            device_id = 0
        if device_id <= 0:
            raise UserError(_('Selecciona una puerta antes de abrir.'))

        Device = self.env['access_control.device'].sudo()
        device = Device.browse(device_id).exists()
        if not device or not device.active:
            raise UserError(_('La puerta seleccionada no existe o está inactiva.'))

        data = dict(options or {})
        try:
            company_id = int(data.get('company_id') or 0)
        except (TypeError, ValueError):
            company_id = 0
        company = self.env['res.company'].sudo().browse(company_id).exists() if company_id else self.env.company
        if company and device.site_id and device.site_id.company_id and device.site_id.company_id.id != company.id:
            raise UserError(_('La puerta seleccionada no pertenece a la empresa activa del Punto de Venta.'))

        if not hasattr(device, 'open_door_via_adms'):
            raise UserError(_('El módulo de control de acceso no tiene disponible el comando de apertura de puerta.'))

        try:
            result = device.open_door_via_adms(
                door_id=data.get('door_id') or data.get('doorId') or 1,
                open_time_seconds=data.get('open_time_seconds') or data.get('openTimeSeconds') or 5,
                reason=data.get('reason') or 'subscription_access_log_button',
                operator_user=self.env.user,
            )
        except UserError:
            raise
        except Exception as error:
            _logger.exception(
                'WGS POS: unexpected error opening access door device_id=%s user_id=%s',
                device.id,
                self.env.user.id,
            )
            raise UserError(_('No se pudo enviar el comando de apertura de puerta. %s') % str(error)) from error
        return result

    @api.model
    def wgs_get_access_event_log_for_pos(self, options=False):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar la bitácora de accesos desde Punto de Venta.'))

        data = dict(options or {})
        try:
            company_id = int(data.get('company_id') or 0)
        except (TypeError, ValueError):
            company_id = 0
        company = self.env['res.company'].sudo().browse(company_id).exists() if company_id else self.env.company
        sites = self._wgs_get_pos_access_sites_for_pos(company)
        Device = self.env['access_control.device'].sudo()
        devices = Device.search(
            [('site_id', 'in', sites.ids), ('active', '=', True)],
            order='name asc, device_serial asc, id asc',
        ) if sites else Device.browse()

        try:
            limit = int(data.get('limit') or 100)
        except (TypeError, ValueError):
            limit = 100
        limit = min(max(limit, 1), 500)

        timezone_name = data.get('timezone') or data.get('time_zone') or False
        default_from, default_to = self._wgs_access_log_default_local_range_for_pos(timezone_name)
        from_dt = self._wgs_parse_access_log_datetime_for_pos(data.get('from'), default_from, timezone_name)
        to_dt = self._wgs_parse_access_log_datetime_for_pos(data.get('to'), default_to, timezone_name)
        if to_dt <= from_dt:
            to_dt = from_dt + timedelta(days=1)
        to_dt_exclusive = to_dt + timedelta(minutes=1)

        domain = [
            ('site_id', 'in', sites.ids),
            ('occurred_at', '>=', fields.Datetime.to_string(from_dt)),
            ('occurred_at', '<', fields.Datetime.to_string(to_dt_exclusive)),
        ]
        result_filter = data.get('result') or 'all'
        if result_filter in ('allowed', 'denied', 'error'):
            domain.append(('result', '=', result_filter))

        try:
            device_id = int(data.get('device_id') or 0)
        except (TypeError, ValueError):
            device_id = 0
        if device_id and device_id in devices.ids:
            domain.append(('device_id', '=', device_id))

        Event = self.env['access_control.access_event'].sudo()
        events = Event.search(domain, order='occurred_at desc, id desc', limit=limit)
        total = Event.search_count(domain)
        result_labels = {
            'allowed': _('Exitoso'),
            'denied': _('Fallido'),
            'error': _('Error'),
        }

        rows = []
        for event in events:
            raw_payload = {}
            if event.raw_payload:
                try:
                    raw_payload = json.loads(event.raw_payload)
                except (TypeError, ValueError):
                    raw_payload = {}
            is_open_door_event = event.modality == 'manual_open_door' or event.event_id.startswith('open_door:')
            partner = event.person_id.partner_id if event.person_id and event.person_id.partner_id else False
            partner_name = partner.display_name if partner else (
                _('Usuario global %s') % event.global_user_id if event.global_user_id else _('Sin identificar')
            )
            if is_open_door_event:
                operator_name = raw_payload.get('operatorUserName') or raw_payload.get('operator_user_name')
                partner_name = _('Apertura por botón por %s') % operator_name if operator_name else _('Apertura por botón')
            result_label = result_labels.get(event.result, event.result or '-')
            if is_open_door_event and event.result == 'allowed':
                result_label = _('Comando enviado')
            rows.append({
                'id': event.id,
                'event_id': event.event_id or False,
                'event_type': 'open_door' if is_open_door_event else 'access',
                'occurred_at': self._wgs_access_log_datetime_to_utc_iso_for_pos(event.occurred_at),
                'site_id': event.site_id.id if event.site_id else False,
                'site_name': event.site_id.display_name if event.site_id else False,
                'device_id': event.device_id.id if event.device_id else False,
                'device_name': event.device_id.display_name if event.device_id else (event.device_serial or False),
                'device_serial': event.device_serial or (event.device_id.device_serial if event.device_id else False),
                'partner_id': partner.id if partner else False,
                'partner_name': partner_name,
                'global_user_id': event.global_user_id or False,
                'result': event.result or False,
                'result_label': result_label,
            })

        return {
            'ok': True,
            'company_id': company.id if company else False,
            'site_ids': sites.ids,
            'site_names': sites.mapped('display_name'),
            'devices': [
                {
                    'id': device.id,
                    'name': device.display_name,
                    'serial': device.device_serial or False,
                    'site_id': device.site_id.id if device.site_id else False,
                    'site_name': device.site_id.display_name if device.site_id else False,
                }
                for device in devices
            ],
            'rows': rows,
            'total': total,
            'limit': limit,
        }

    @api.model
    def wgs_resync_subscription_access_for_pos(self, subscription_id):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para resincronizar acceso desde Punto de Venta.'))

        subscription = self._wgs_browse_subscription_for_pos(subscription_id)
        if not subscription:
            raise AccessError(_('La suscripción seleccionada no existe.'))
        if not subscription._is_subscription_record_for_pos():
            raise AccessError(_('La orden seleccionada no corresponde a una suscripción válida.'))

        self.env.cr.execute('SELECT id FROM sale_order WHERE id = %s FOR UPDATE', [subscription.id])
        ICP = self.env['ir.config_parameter'].sudo()
        cooldown_key = 'witann_group_subscriptions_pos.access_resync_last_at.%s' % subscription.id
        now = fields.Datetime.now()
        last_resync_raw = ICP.get_param(cooldown_key)
        last_resync = fields.Datetime.to_datetime(last_resync_raw) if last_resync_raw else False
        if last_resync:
            elapsed = (now - last_resync).total_seconds()
            remaining = int(self._WGS_POS_ACCESS_RESYNC_COOLDOWN_SECONDS - elapsed)
            if remaining > 0:
                raise UserError(
                    _('Espera %s segundos antes de volver a resincronizar el acceso de esta suscripción.') % remaining
                )
        ICP.set_param(cooldown_key, fields.Datetime.to_string(now))

        Change = self.env['access_control.sync_change'].sudo()
        last_change = Change.search([], order='id desc', limit=1)
        last_change_id = last_change.id or 0

        if hasattr(subscription, '_ensure_subscription_owner_is_participant'):
            subscription._ensure_subscription_owner_is_participant()
        if hasattr(subscription, '_wgs_sync_access_control_people'):
            subscription.with_context(access_sync_priority=True)._wgs_sync_access_control_people()

        partners = self._wgs_partner_model_for_pos().browse(sorted(subscription._wgs_get_access_related_partner_ids())).exists()
        if partners and hasattr(partners, '_sync_access_person_face'):
            partners.with_context(access_sync_priority=True)._sync_access_person_face()

        manual_resync_changes = Change.search([
            ('id', '>', last_change_id),
            ('action', 'in', ('upsert', 'delete')),
        ])
        if manual_resync_changes:
            manual_resync_changes.write({'priority': True})
            _logger.info(
                'WGS POS access resync marked priority subscription_id=%s change_ids=%s',
                subscription.id,
                manual_resync_changes.ids,
            )

        return {
            'ok': True,
            'subscription_id': subscription.id,
            'access_summary': subscription._wgs_get_access_people_summary_for_pos(),
            'cooldown_seconds': self._WGS_POS_ACCESS_RESYNC_COOLDOWN_SECONDS,
        }

    def _wgs_get_access_people_summary_for_pos(self):
        self.ensure_one()
        partner_ids = sorted(self._wgs_get_access_related_partner_ids())
        if not partner_ids:
            return {
                'person_count': 0,
                'active_count': 0,
                'suspended_count': 0,
                'missing_count': 0,
                'site_names': [],
                'people': [],
            }

        partners = self._wgs_partner_model_for_pos().browse(partner_ids).exists()
        Person = self._wgs_person_model_for_pos()
        people = Person.search([('partner_id', 'in', partners.ids)], order='partner_id asc, id asc')
        people_by_partner = {person.partner_id.id: person for person in people}

        rows = []
        site_names = set()
        active_count = 0
        suspended_count = 0
        missing_count = 0

        for partner in partners:
            person = people_by_partner.get(partner.id)
            if not person:
                missing_count += 1
                rows.append({
                    'partner_id': partner.id,
                    'partner_name': partner.display_name,
                    'person_id': False,
                    'active': False,
                    'access_state': False,
                    'global_user_id': False,
                    'site_names': [],
                    'managed_by_subscription': False,
                })
                continue

            current_site_names = person.site_ids.mapped('name')
            site_names.update(current_site_names)
            if person.active:
                active_count += 1
            elif person.access_state == 'suspended':
                suspended_count += 1
            rows.append({
                'partner_id': partner.id,
                'partner_name': partner.display_name,
                'person_id': person.id,
                'active': bool(person.active),
                'access_state': person.access_state or False,
                'global_user_id': person.global_user_id or False,
                'site_names': current_site_names,
                'managed_by_subscription': bool(person.managed_by_subscription),
            })

        return {
            'person_count': len(people),
            'active_count': active_count,
            'suspended_count': suspended_count,
            'missing_count': missing_count,
            'site_names': sorted(site_names),
            'people': rows,
        }

    @api.model
    def get_partner_subscription_status_map_for_pos(self, partner_ids):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar vigencia desde Punto de Venta.'))

        partner_ids = [int(pid) for pid in (partner_ids or []) if pid]
        if not partner_ids:
            return {}

        partners = self._wgs_partner_model_for_pos().browse(partner_ids).exists()
        if not partners:
            return {}

        today = fields.Date.context_today(self)
        subscriptions_by_partner = self._get_pos_subscription_orders_by_partners(partners)
        try:
            access_last_map = self._get_access_person_last_access_map_for_pos(partners)
        except Exception as error:
            self._wgs_raise_pos_data_error(
                _('No se pudo consultar la información de acceso para construir el directorio de suscripciones.'),
                error=error,
                partner_ids=partner_ids,
            )

        result = {}
        for partner in partners:
            subscriptions = subscriptions_by_partner.get(partner.id, self.browse())
            items = []
            for subscription in subscriptions:
                try:
                    item = subscription._build_pos_subscription_status_item(today)
                except Exception as error:
                    self._wgs_raise_pos_data_error(
                        _('No se pudo construir el estado de suscripciones para uno de los clientes del directorio.'),
                        error=error,
                        subscription_id=subscription.id,
                        partner_id=partner.id,
                    )
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
    def _get_partner_subscription_directory_status_map_for_pos(self, partners, include_profile_fields=True):
        if not partners:
            return {}

        today = fields.Date.context_today(self)
        subscriptions_by_partner = self._get_pos_subscription_orders_by_partners(partners)
        access_last_map = {}
        if include_profile_fields:
            try:
                access_last_map = self._get_access_person_last_access_map_for_pos(partners)
            except Exception as error:
                self._wgs_raise_pos_data_error(
                    _('No se pudo consultar la información de acceso para construir el directorio de suscripciones.'),
                    error=error,
                    partner_ids=partners.ids,
                )

        result = {}
        for partner in partners:
            subscriptions = subscriptions_by_partner.get(partner.id, self.browse())
            items = []
            for subscription in subscriptions:
                try:
                    item = subscription._build_pos_subscription_directory_status_item(today)
                except Exception as error:
                    self._wgs_raise_pos_data_error(
                        _('No se pudo construir la fila del directorio de suscripciones.'),
                        error=error,
                        subscription_id=subscription.id,
                        partner_id=partner.id,
                    )
                if item:
                    items.append(item)

            summary = self._summarize_partner_subscription_items_for_pos(items)
            values = {
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
            }

            if include_profile_fields:
                phone_value = self._get_partner_field_value_for_pos(partner, ('phone', 'mobile'))
                email_value = self._get_partner_field_value_for_pos(partner, ('email',))
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

                values.update({
                    'phone': phone_value or False,
                    'email': email_value or False,
                    'gender': gender_value or False,
                    'birthday': birthday_value or False,
                    'last_access': last_access_value or False,
                    'image_url': '/web/image/res.partner/%s/image_128' % partner.id,
                })

            result[partner.id] = values

        return result

    @api.model
    def get_partner_directory_summary_for_pos(self):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar vigencia desde Punto de Venta.'))

        Partner = self._wgs_partner_model_for_pos()
        total = Partner.search_count([])
        birthday_field = self._get_partner_directory_birthday_field_for_pos()
        birthday_count = Partner.search_count([(birthday_field, '!=', False)]) if birthday_field else 0

        subscriptions = self.sudo().search(self._get_subscription_action_domain_for_pos(), order='id desc')
        subscriptions = subscriptions.filtered(lambda order: order._is_subscription_record_for_pos())
        today = fields.Date.context_today(self)
        items_by_partner_id = {}

        for subscription in subscriptions:
            try:
                item = subscription._build_pos_subscription_directory_status_item(today)
            except Exception as error:
                self._wgs_raise_pos_data_error(
                    _('No se pudo construir el resumen del directorio de suscripciones.'),
                    error=error,
                    subscription_id=subscription.id,
                )
            if not item:
                continue
            partner_ids = set(subscription.participant_ids.ids)
            if subscription.partner_id:
                partner_ids.add(subscription.partner_id.id)
            for partner_id in partner_ids:
                items_by_partner_id.setdefault(partner_id, []).append(item)

        counts = {
            'total': total,
            'birthday': birthday_count,
            'progress': 0,
            'renew': 0,
            'paused': 0,
            'draft': 0,
            'cancel': 0,
            'closed': 0,
            'upsell': 0,
            'other': 0,
            'none': 0,
        }
        for items in items_by_partner_id.values():
            summary = self._summarize_partner_subscription_items_for_pos(items)
            state = summary.get('state') or 'none'
            if state == 'closed':
                counts['closed'] += 1
                counts['cancel'] += 1
            elif state in counts:
                counts[state] += 1
            else:
                counts['other'] += 1

        counts['none'] = max(total - len(items_by_partner_id), 0)
        return counts

    @api.model
    def get_partner_directory_rows_for_pos(self, offset=0, limit=500, state_filter=False, search_term=False):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar vigencia desde Punto de Venta.'))

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

        partners = self._get_partner_directory_partners_for_pos(
            offset=max(offset, 0),
            limit=limit,
            state_filter=state_filter,
            search_term=search_term,
        )
        if not partners:
            return []

        try:
            status_map = self._get_partner_subscription_directory_status_map_for_pos(partners)
        except Exception as error:
            self._wgs_raise_pos_data_error(
                _('No se pudo construir el directorio de suscripciones en este momento.'),
                error=error,
                offset=offset,
                limit=limit,
            )
        rows = []
        for partner in partners:
            status = status_map.get(partner.id, {})
            rows.append(self._wgs_build_partner_directory_row_for_pos(partner, status))
        return rows

    @api.model
    def get_partner_directory_row_for_pos(self, partner_id):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar vigencia desde Punto de Venta.'))

        partner = self._wgs_browse_partner_for_pos(partner_id)
        if not partner:
            return {}

        try:
            status_map = self._get_partner_subscription_directory_status_map_for_pos(partner)
        except Exception as error:
            self._wgs_raise_pos_data_error(
                _('No se pudo construir la fila del directorio de suscripciones.'),
                error=error,
                partner_id=partner.id,
            )
        return self._wgs_build_partner_directory_row_for_pos(partner, status_map.get(partner.id, {}))

    @api.model
    def search_subscription_participants_for_pos(self, search_term=False, limit=120):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar participantes desde Punto de Venta.'))

        Partner = self._wgs_partner_model_for_pos()
        try:
            limit = int(limit or 120)
        except (TypeError, ValueError):
            limit = 120
        limit = min(max(limit, 1), 3000)

        search_partner_ids = self._get_partner_ids_matching_directory_search_for_pos(search_term)
        domain = []
        if search_partner_ids is not False:
            if not search_partner_ids:
                return []
            domain.append(('id', 'in', search_partner_ids))

        partners = Partner.search(domain, order='name asc, id asc', limit=limit)
        rows = []
        for partner in partners:
            phone = self._get_partner_field_value_for_pos(partner, ('phone', 'mobile'))
            email = self._get_partner_field_value_for_pos(partner, ('email',))
            rows.append({
                'id': partner.id,
                'name': partner.display_name,
                'email': email or False,
                'phone': phone or False,
                'image_url': '/web/image/res.partner/%s/image_128' % partner.id,
            })
        return rows

    @api.model
    def _wgs_build_partner_directory_row_for_pos(self, partner, status):
        partner.ensure_one()
        status = dict(status or {})
        phone_fallback = False
        if 'phone' in partner._fields:
            phone_fallback = partner.phone or False
        return {
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
        }

    @api.model
    def _get_partner_directory_partners_for_pos(self, offset=0, limit=500, state_filter=False, search_term=False):
        Partner = self._wgs_partner_model_for_pos()
        state_filter = self._normalize_partner_directory_state_filter_for_pos(state_filter)
        search_partner_ids = self._get_partner_ids_matching_directory_search_for_pos(search_term)
        partner_domain = []
        if search_partner_ids is not False:
            if not search_partner_ids:
                return Partner
            partner_domain = [('id', 'in', search_partner_ids)]

        if state_filter == 'all':
            return Partner.search(
                partner_domain,
                order='name asc, id asc',
                offset=offset,
                limit=limit,
            )

        if state_filter == 'none':
            related_partner_ids = self._get_partner_ids_with_pos_subscriptions_for_pos()
            domain = list(partner_domain)
            if related_partner_ids:
                domain.append(('id', 'not in', related_partner_ids))
            return Partner.search(domain, order='name asc, id asc', offset=offset, limit=limit)

        candidate_partner_ids = self._get_partner_ids_for_directory_state_fast_path_for_pos(state_filter)
        if candidate_partner_ids:
            domain = list(partner_domain) + [('id', 'in', candidate_partner_ids)]
            return self._search_partner_directory_candidate_state_page_for_pos(
                partner_domain=domain,
                state_filter=state_filter,
                offset=offset,
                limit=limit,
            )

        return Partner

    @api.model
    def _normalize_partner_directory_state_filter_for_pos(self, state_filter):
        state_filter = str(state_filter or 'actionable').strip().lower()
        allowed = set(self._WGS_POS_SUBSCRIPTION_STATE_PRIORITY) | {'all', 'actionable'}
        return state_filter if state_filter in allowed else 'actionable'

    @api.model
    def _directory_state_matches_filter_for_pos(self, state, state_filter):
        state = state or 'none'
        state_filter = self._normalize_partner_directory_state_filter_for_pos(state_filter)
        if state_filter == 'all':
            return True
        state_values = self._WGS_POS_DIRECTORY_STATE_ALIASES.get(state_filter, (state_filter,))
        return state in state_values

    @api.model
    def _get_partner_directory_search_domain_for_pos(self, search_term=False):
        search_term = (search_term or '').strip()
        if not search_term:
            return []

        Partner = self._wgs_partner_model_for_pos()
        leaves = [('name', 'ilike', search_term)]
        for field_name in ('phone', 'mobile', 'email'):
            if field_name in Partner._fields:
                leaves.append((field_name, 'ilike', search_term))
        return self._wgs_or_leaves_for_pos(leaves)

    @api.model
    def _get_partner_ids_matching_directory_search_for_pos(self, search_term=False):
        search_term = (search_term or '').strip()
        if not search_term:
            return False

        Partner = self._wgs_partner_model_for_pos()
        partner_ids = set(Partner.search(self._get_partner_directory_search_domain_for_pos(search_term)).ids)

        subscriptions = self.sudo().search(self._get_subscription_action_domain_for_pos())
        subscriptions = subscriptions.filtered(lambda order: order._is_subscription_record_for_pos())
        if subscriptions:
            recurring_lines = subscriptions.order_line.filtered(
                lambda line: line.product_id
                and line.product_id.product_tmpl_id.recurring_invoice
                and (
                    search_term.lower() in (line.product_id.display_name or '').lower()
                    or search_term.lower() in (line.name or '').lower()
                )
            )
            for subscription in recurring_lines.mapped('order_id'):
                partner_ids.update(subscription.participant_ids.ids)
                if subscription.partner_id:
                    partner_ids.add(subscription.partner_id.id)

        return sorted(partner_ids)

    @api.model
    def _get_partner_directory_birthday_field_for_pos(self):
        Partner = self._wgs_partner_model_for_pos()
        for field_name in self._PARTNER_BIRTHDAY_FIELD_CANDIDATES:
            if field_name in Partner._fields:
                return field_name
        return False

    @api.model
    def _get_partner_ids_with_pos_subscriptions_for_pos(self):
        subscriptions = self.sudo().search(self._get_subscription_action_domain_for_pos())
        subscriptions = subscriptions.filtered(lambda order: order._is_subscription_record_for_pos())
        partner_ids = set()
        for subscription in subscriptions:
            partner_ids.update(subscription.participant_ids.ids)
            if subscription.partner_id:
                partner_ids.add(subscription.partner_id.id)
        return sorted(partner_ids)

    @api.model
    def _get_partner_ids_for_directory_state_fast_path_for_pos(self, state_filter):
        subscription_state_domain = self._get_subscription_state_domain_for_directory_filter_for_pos(state_filter)
        if subscription_state_domain is False:
            return []

        domain = fields.Domain.AND([
            self._get_subscription_action_domain_for_pos(),
            subscription_state_domain,
        ])
        subscriptions = self.sudo().search(domain, order='id desc')
        subscriptions = subscriptions.filtered(lambda order: order._is_subscription_record_for_pos())
        partner_ids = set()
        for subscription in subscriptions:
            partner_ids.update(subscription.participant_ids.ids)
            if subscription.partner_id:
                partner_ids.add(subscription.partner_id.id)
        return sorted(partner_ids)

    @api.model
    def _get_subscription_state_domain_for_directory_filter_for_pos(self, state_filter):
        if 'subscription_state' not in self._fields:
            return False

        state_filter = self._normalize_partner_directory_state_filter_for_pos(state_filter)
        token_map = {
            'actionable': ('progress', 'renew'),
            'progress': ('progress',),
            'renew': ('progress', 'renew'),
            'cancel': ('cancel', 'canceled', 'cancelled', 'close', 'closed', 'churn', 'churned'),
        }
        tokens = token_map.get(state_filter)
        if not tokens:
            return False
        return self._wgs_or_leaves_for_pos([('subscription_state', 'ilike', token) for token in tokens])

    @api.model
    def _search_partner_directory_candidate_state_page_for_pos(self, partner_domain, state_filter, offset=0, limit=500):
        Partner = self._wgs_partner_model_for_pos()
        partner_domain = list(partner_domain or [])
        offset = max(int(offset or 0), 0)
        limit = max(int(limit or 500), 1)
        scan_limit = min(max(limit * 2, 120), 500)
        selected_ids = []
        skipped_matches = 0
        partner_offset = 0

        while len(selected_ids) < limit:
            partners = Partner.search(
                partner_domain,
                order='name asc, id asc',
                offset=partner_offset,
                limit=scan_limit,
            )
            if not partners:
                break

            status_map = self._get_partner_subscription_directory_status_map_for_pos(
                partners,
                include_profile_fields=False,
            )
            for partner in partners:
                state = status_map.get(partner.id, {}).get('state') or 'none'
                if not self._directory_state_matches_filter_for_pos(state, state_filter):
                    continue
                if skipped_matches < offset:
                    skipped_matches += 1
                    continue
                selected_ids.append(partner.id)
                if len(selected_ids) >= limit:
                    break

            if len(partners) < scan_limit:
                break
            partner_offset += len(partners)

        return Partner.browse(selected_ids).exists()

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
        domain = self._wgs_and_domains_for_pos(
            self._get_subscription_action_domain_for_pos(),
            partner_domain,
        )

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
        domain = self._wgs_and_domains_for_pos(
            self._get_subscription_action_domain_for_pos(),
            partner_domain,
        )

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
        return base_domain

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

    def _build_pos_subscription_directory_status_item(self, today):
        self.ensure_one()

        recurring_lines = self._get_recurring_lines()
        if not recurring_lines:
            return False

        primary_recurring_line = recurring_lines.sorted(key=lambda line: line.id)[:1]
        plan_name = self._get_subscription_plan_name_for_pos(recurring_lines)
        access_state = self._classify_subscription_access_state_for_pos()
        native_state_key, native_state_label = self._get_native_subscription_state_info_for_pos()

        start_date = self._get_first_available_date(
            ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date', 'date_order')
        )
        next_invoice_date = self._get_first_available_date(
            ('recurring_next_date', 'next_invoice_date', 'recurring_next_invoice_date')
        )
        hard_end_date = self._get_first_available_date(
            ('date_end', 'end_date', 'subscription_end_date', 'recurring_end_date')
        )
        recurrence_delta = self._get_recurrence_delta()

        if start_date and (not next_invoice_date or next_invoice_date <= start_date):
            next_invoice_date = start_date + recurrence_delta

        period_start = False
        valid_until = False
        if next_invoice_date:
            period_start = next_invoice_date - recurrence_delta
            valid_until = next_invoice_date - relativedelta(days=1)
        if hard_end_date and (not valid_until or hard_end_date < valid_until):
            valid_until = hard_end_date

        reason = _('La suscripción no está vigente para control de acceso.')
        if start_date and start_date > today:
            access_state = False
            reason = _('La suscripción todavía no inicia.')
        elif native_state_key in ('cancel', 'closed'):
            access_state = False
            reason = _('La suscripción está cancelada o cerrada y puede reinscribirse.')
        elif next_invoice_date and next_invoice_date <= today:
            native_state_key = 'renew'
            native_state_label = _('Por renovar')
            reason = _('La suscripción sigue activa, pero ya venció su siguiente fecha de cobro y debe renovarse.')
        elif access_state == 'enabled':
            reason = _('Suscripción en progreso o en renovación.')
        elif access_state == 'suspended':
            reason = _('La suscripción está pausada o suspendida.')

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
            'renewal_product_id': primary_recurring_line.product_id.id if primary_recurring_line else False,
            'start_date': start_date.isoformat() if start_date else False,
            'period_start': period_start.isoformat() if period_start else False,
            'valid_until': valid_until.isoformat() if valid_until else False,
            'next_invoice_date': next_invoice_date.isoformat() if next_invoice_date else False,
            'is_valid': access_state == 'enabled',
            'status_label': _('Vigente') if access_state == 'enabled' else _('Sin vigencia'),
            'reason': reason,
        }

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
        next_invoice_date = self._get_first_available_date(
            ('recurring_next_date', 'next_invoice_date', 'recurring_next_invoice_date')
        )
        hard_end_date = self._get_first_available_date(
            ('date_end', 'end_date', 'subscription_end_date', 'recurring_end_date')
        )
        has_replacement_subscription = self._wgs_has_replacement_subscription_for_pos()

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

        should_mark_for_renewal = bool(next_invoice_date and next_invoice_date <= today)

        force_closed = bool(has_replacement_subscription)

        can_renew = False
        can_reenroll = False

        if force_closed:
            access_state = False
            is_valid = False
            native_state_key = 'closed'
            native_state_label = _('Cerrada')
            reason = _('La suscripción fue reemplazada por un upsale posterior.')
        elif start_date and start_date > today:
            access_state = False
            is_valid = False
            reason = _('La suscripción todavía no inicia.')
        elif native_state_key in ('cancel', 'closed'):
            access_state = False
            is_valid = False
            reason = _('La suscripción está cancelada o cerrada y puede reinscribirse.')
        elif should_mark_for_renewal:
            native_state_key = 'renew'
            native_state_label = _('Por renovar')
            is_valid = True
            can_renew = True
            reason = _('La suscripción sigue activa, pero ya venció su siguiente fecha de cobro y debe renovarse.')
        elif access_state == 'enabled':
            is_valid = True
            can_renew = True
            reason = _('Suscripción en progreso o en renovación.')
        elif access_state == 'suspended':
            reason = _('La suscripción está pausada o suspendida.')
        else:
            reason = _('La suscripción no está en progreso ni en renovación.')

        if native_state_key in ('cancel', 'closed') and not force_closed:
            can_reenroll = True

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
            'has_replacement_subscription': bool(has_replacement_subscription),
            'can_renew': bool(can_renew),
            'can_reenroll': bool(can_reenroll),
        }

    def _wgs_has_replacement_subscription_for_pos(self):
        self.ensure_one()
        sale_order_model = self.sudo()
        fields_map = sale_order_model._fields
        relation_field_names = []

        pos_line_model_name = 'pos.order.line'
        if pos_line_model_name in self.env.registry:
            pos_line_model = self.env[pos_line_model_name].sudo()
            pos_line_domain = [('wgs_subscription_source_id', '=', self.id)]
            if 'wgs_subscription_flow' in pos_line_model._fields:
                pos_line_domain.append(('wgs_subscription_flow', '=', 'upsale'))
            if 'order_id' in pos_line_model._fields:
                pos_line_domain.append(('order_id.state', 'not in', ('draft', 'cancel')))
            replacement_lines = pos_line_model.search(pos_line_domain, order='id desc')
            replacement_orders = replacement_lines.mapped('wgs_sale_order_id').filtered(
                lambda order: order
                and order != self
                and order._is_subscription_record_for_pos()
                and (
                    not self.partner_id
                    or not order.partner_id
                    or order.partner_id.id == self.partner_id.id
                )
            )
            if replacement_orders:
                return True

        for field_name in ('subscription_id', 'origin_order_id', 'note_order'):
            field = fields_map.get(field_name)
            if field and field.type == 'many2one' and getattr(field, 'comodel_name', '') == 'sale.order':
                relation_field_names.append(field_name)

        for field_name, field in fields_map.items():
            if field_name in relation_field_names:
                continue
            if field.type != 'many2one' or getattr(field, 'comodel_name', '') != 'sale.order':
                continue
            normalized_name = (field_name or '').lower()
            if any(token in normalized_name for token in ('subscription', 'origin', 'upsell', 'note')):
                relation_field_names.append(field_name)

        if not relation_field_names:
            return False

        candidates = sale_order_model.browse()
        for field_name in relation_field_names:
            domain = [
                (field_name, '=', self.id),
                ('state', 'in', ['sale', 'done']),
                ('id', '!=', self.id),
            ]
            if self.partner_id and 'partner_id' in fields_map:
                domain.append(('partner_id', '=', self.partner_id.id))
            candidates |= sale_order_model.search(domain, order='id desc')

        if not candidates:
            return False

        replacement_orders = candidates.filtered(
            lambda order: order._is_subscription_record_for_pos()
            and (
                not self.partner_id
                or not order.partner_id
                or order.partner_id.id == self.partner_id.id
            )
        )
        return bool(replacement_orders)

    @api.model
    def _should_display_subscription_item_in_pos_detail(self, item, today=False):
        if not item:
            return False

        today = today or fields.Date.context_today(self)
        native_state_key = item.get('native_state_key') or False
        if item.get('has_replacement_subscription'):
            return False

        if native_state_key in ('draft', 'upsell'):
            return False

        if native_state_key in ('closed', 'cancel'):
            return True

        # Renewable/re-enrollable subscriptions must stay visible in the
        # detail pane even if their current period already expired.
        if item.get('can_renew') or item.get('can_reenroll'):
            return True

        access_state = item.get('access_state') or False
        if access_state in ('enabled', 'suspended'):
            return True

        start_date = self._to_date(item.get('start_date'))
        if start_date and start_date >= today:
            return True

        valid_until = self._to_date(item.get('valid_until'))
        if valid_until and valid_until >= today:
            return True

        return False

    @api.model
    def _filter_partner_subscription_detail_items_for_pos(self, items):
        visible_items = list(items or [])
        prioritized_items = [
            item
            for item in visible_items
            if self._get_subscription_detail_business_priority_for_pos(item) is not False
        ]
        if len(prioritized_items) <= 1:
            return [self._strip_subscription_detail_internal_keys_for_pos(item) for item in visible_items]

        best_priority = min(
            self._get_subscription_detail_business_priority_for_pos(item)
            for item in prioritized_items
        )
        same_priority_items = [
            item
            for item in prioritized_items
            if self._get_subscription_detail_business_priority_for_pos(item) == best_priority
        ]
        latest_item = max(
            same_priority_items,
            key=lambda item: item.get('_wgs_creation_sort_key') or ('', 0),
        )
        latest_subscription_id = latest_item.get('subscription_id')
        filtered_items = [
            item
            for item in visible_items
            if (
                self._get_subscription_detail_business_priority_for_pos(item) is False
                or item.get('subscription_id') == latest_subscription_id
            )
        ]
        return [self._strip_subscription_detail_internal_keys_for_pos(item) for item in filtered_items]

    @api.model
    def _get_subscription_detail_business_priority_for_pos(self, item):
        native_state_key = item.get('native_state_key') or False
        if native_state_key == 'progress':
            return 0
        if native_state_key == 'renew':
            return 1
        if native_state_key in ('cancel', 'closed') or item.get('can_reenroll'):
            return 2
        return False

    @api.model
    def _get_subscription_detail_creation_sort_key_for_pos(self, subscription):
        create_date = getattr(subscription, 'create_date', False)
        create_date_value = fields.Datetime.to_string(create_date) if create_date else ''
        return (create_date_value, subscription.id or 0)

    @api.model
    def _strip_subscription_detail_internal_keys_for_pos(self, item):
        cleaned = dict(item or {})
        cleaned.pop('_wgs_creation_sort_key', None)
        return cleaned

    def _wgs_get_pending_invoice_records_for_pos(self):
        self.ensure_one()
        account_move_model = self._wgs_account_move_model_for_pos()
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
            return 'progress', _('En progreso')
        if any(token in haystack for token in ('renew', 'to renew', 'por renovar')):
            return 'renew', _('Por renovar')
        if any(token in haystack for token in self._WGS_ACCESS_SUSPENDED_STATE_TOKENS):
            return 'paused', _('Pausada')
        if any(token in haystack for token in ('draft', 'borrador')):
            return 'draft', _('Borrador')
        if any(token in haystack for token in ('cancel', 'cancelled', 'canceled', 'cancelada')):
            return 'cancel', _('Cancelada')
        if any(token in haystack for token in ('close', 'closed', 'cerrada', 'churn', 'churned')):
            return 'closed', _('Cerrada')
        if 'upsell' in haystack:
            return 'upsell', _('Upsell')
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
            if 'wgs_single_day_plan' in plan._fields and plan.wgs_single_day_plan:
                interval = 1
                unit = 'day'
            elif {'recurring_interval', 'recurring_rule_type'}.issubset(plan._fields):
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

    def _get_partner_curp_for_pos(self, partner):
        partner.ensure_one()
        if hasattr(partner, '_wgs_get_curp_value'):
            return partner._wgs_get_curp_value()
        return self._get_partner_field_value_for_pos(partner, self._PARTNER_CURP_FIELD_CANDIDATES)

    def _wgs_get_partner_curp_field_for_pos(self, partner_model=None):
        Partner = partner_model or self._wgs_partner_model_for_pos()
        if hasattr(Partner, '_wgs_get_curp_field_name'):
            field_name = Partner._wgs_get_curp_field_name()
            if field_name and Partner._fields.get(field_name):
                return field_name
        for field_name in self._PARTNER_CURP_FIELD_CANDIDATES:
            if Partner._fields.get(field_name):
                return field_name
        return False

    def _wgs_normalize_partner_curp_for_pos(self, curp):
        Partner = self._wgs_partner_model_for_pos()
        if hasattr(Partner, '_wgs_normalize_curp'):
            return Partner._wgs_normalize_curp(curp)
        if not curp:
            return False
        return re.sub(r'[\s-]+', '', str(curp)).upper() or False

    def _wgs_validate_partner_curp_for_pos(self, curp, exclude_partner=False):
        Partner = self._wgs_partner_model_for_pos()
        curp_field = self._wgs_get_partner_curp_field_for_pos(Partner)
        if not curp_field:
            return {
                'ok': False,
                'message': _('Este entorno no permite capturar CURP desde Punto de Venta.'),
            }

        normalized = self._wgs_normalize_partner_curp_for_pos(curp)
        if not normalized:
            return {
                'ok': False,
                'message': _('Debes capturar una CURP válida.'),
            }

        domain = [(curp_field, '=', normalized)]
        if exclude_partner:
            domain.insert(0, ('id', '!=', exclude_partner.id))
        duplicate = Partner.search(domain, limit=1)
        if duplicate:
            return {
                'ok': False,
                'message': _(
                    'La CURP %(curp)s ya está asignada al contacto %(partner)s. '
                    'No se permiten contactos duplicados con la misma CURP.'
                ) % {
                    'curp': normalized,
                    'partner': duplicate.display_name,
                },
            }
        return {
            'ok': True,
            'normalized': normalized,
        }

    def _assign_partner_field_for_pos(self, partner_model, values, field_candidates, raw_value):
        raw_value = raw_value if raw_value not in (None, '') else False
        if raw_value is False:
            return False

        for field_name in field_candidates:
            field = partner_model._fields.get(field_name)
            if not field:
                continue

            formatted_value = raw_value
            if field.type == 'selection':
                formatted_value = self._map_partner_selection_value_for_pos(field, raw_value)
                if formatted_value in (False, None, ''):
                    continue
            elif field.type == 'date':
                converted = fields.Date.to_date(raw_value)
                if not converted:
                    continue
                formatted_value = fields.Date.to_string(converted)
            elif field.type not in ('char', 'text'):
                continue

            values[field_name] = formatted_value
            return field_name
        return False

    def _assign_or_clear_partner_field_for_pos(self, partner_model, values, field_candidates, raw_value):
        raw_value = raw_value if raw_value not in (None, '') else False
        if raw_value is False:
            for field_name in field_candidates:
                if partner_model._fields.get(field_name):
                    values[field_name] = False
                    return field_name
            return False
        return self._assign_partner_field_for_pos(partner_model, values, field_candidates, raw_value)

    def _map_partner_selection_value_for_pos(self, field, raw_value):
        normalized = str(raw_value or '').strip().lower()
        if not normalized:
            return False

        selection = field._description_selection(self.env) if callable(field.selection) else field.selection
        options = list(selection or [])
        if not options:
            return False

        wanted_tokens = {
            'male': ('male', 'masculino', 'hombre', 'varon', 'm'),
            'female': ('female', 'femenino', 'mujer', 'f'),
            'other': ('other', 'otro', 'otra', 'no binario', 'nobinario', 'x'),
        }
        target_tokens = wanted_tokens.get(normalized, (normalized,))
        for key, label in options:
            haystack = ' '.join(filter(None, [str(key).lower(), str(label).lower()]))
            if any(token in haystack for token in target_tokens):
                return key
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
