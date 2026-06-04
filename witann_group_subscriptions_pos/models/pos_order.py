import json
import logging
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.fields import Command
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _wgs_get_product_company_domain_for_pos(self, product_model=None):
        product_model = product_model or self.env['product.product']
        company = self.company_id
        if not company:
            return []
        if 'company_id' in product_model._fields:
            return ['|', ('company_id', '=', False), ('company_id', '=', company.id)]
        template_model = self.env['product.template']
        if 'company_id' in template_model._fields:
            return ['|', ('product_tmpl_id.company_id', '=', False), ('product_tmpl_id.company_id', '=', company.id)]
        return []

    def _loader_params_product_product(self):
        parent_loader = getattr(super(), '_loader_params_product_product', None)
        params = parent_loader() if parent_loader else {'search_params': {}}
        search_params = params.setdefault('search_params', {})
        field_list = search_params.setdefault('fields', [])
        domain = search_params.get('domain') or []

        for field_name in (
            'recurring_invoice',
            'is_subscription',
            'subscription_ok',
            'max_participants_total',
        ):
            if field_name not in field_list:
                field_list.append(field_name)

        recurring_domain = [('recurring_invoice', '=', True)]
        if 'recurring_invoice' not in self.env['product.product']._fields:
            recurring_domain = [('product_tmpl_id.recurring_invoice', '=', True)]
        combined_domain = fields.Domain.OR([domain, recurring_domain])
        company_domain = self._wgs_get_product_company_domain_for_pos(self.env['product.product'])
        if company_domain:
            combined_domain = fields.Domain.AND([combined_domain, company_domain])
        search_params['domain'] = combined_domain
        return params


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    wgs_participant_ids_json = fields.Text(string='Participantes de suscripción (POS)', copy=False)
    wgs_pricing_snapshot_json = fields.Text(string='Snapshot pricing suscripción (POS)', copy=False)
    wgs_sale_order_id = fields.Many2one('sale.order', string='Suscripción generada', copy=False)
    wgs_subscription_plan_id = fields.Integer(string='Plan de suscripción (POS)', copy=False)
    wgs_subscription_pricing_id = fields.Integer(string='Tarifa de suscripción (POS)', copy=False)
    wgs_subscription_start_date = fields.Date(string='Fecha inicio de suscripción (POS)', copy=False)
    wgs_subscription_end_date = fields.Date(string='Fecha fin de suscripción (POS)', copy=False)
    wgs_subscription_flow = fields.Selection(
        selection=[
            ('new', 'Nueva suscripción'),
            ('renewal', 'Renovación recurrente'),
            ('reenroll', 'Reinscripción'),
            ('upsale', 'Upsale inmediato'),
            ('pending_charge', 'Cobro pendiente'),
            ('cancellation_refund', 'Cancelación con devolución'),
        ],
        string='Flujo suscripción (POS)',
        default='new',
        copy=False,
    )
    wgs_subscription_source_id = fields.Many2one(
        'sale.order',
        string='Suscripción origen (POS)',
        copy=False,
    )
    wgs_subscription_pending_move_id = fields.Many2one(
        'account.move',
        string='Documento pendiente (POS)',
        copy=False,
    )
    wgs_subscription_refund_origin_line_id = fields.Many2one(
        'pos.order.line',
        string='Línea POS origen para devolución (POS)',
        copy=False,
    )
    wgs_discount_code = fields.Char(string='Código de descuento WGS', copy=False)
    wgs_discount_label = fields.Char(string='Etiqueta descuento WGS', copy=False)
    wgs_discount_percent = fields.Float(string='Porcentaje descuento WGS', copy=False)
    wgs_discount_fixed_amount = fields.Float(string='Monto fijo descuento WGS', copy=False)
    wgs_discount_authorized_employee_id = fields.Many2one(
        'hr.employee',
        string='Autorizado por empleado WGS',
        copy=False,
    )
    wgs_discount_authorized_by = fields.Char(string='Autorizado por WGS', copy=False)
    wgs_discount_authorized_at = fields.Datetime(string='Fecha autorización WGS', copy=False)
    wgs_discount_birthday_year = fields.Integer(string='Año descuento cumpleaños WGS', copy=False)

    def wgs_get_participant_ids(self):
        self.ensure_one()
        raw_value = self.wgs_participant_ids_json or '[]'
        try:
            values = json.loads(raw_value)
        except (TypeError, ValueError):
            return []

        if not isinstance(values, list):
            return []

        participant_ids = []
        for value in values:
            try:
                participant_id = int(value)
            except (TypeError, ValueError):
                continue
            if participant_id > 0:
                participant_ids.append(participant_id)

        # preserve order and uniqueness
        return list(dict.fromkeys(participant_ids))

    def wgs_get_subscription_end_date(self):
        self.ensure_one()
        if not self.wgs_subscription_end_date:
            return False
        return fields.Date.to_date(self.wgs_subscription_end_date)

    def wgs_get_subscription_start_date(self):
        self.ensure_one()
        if not self.wgs_subscription_start_date:
            return False
        return fields.Date.to_date(self.wgs_subscription_start_date)

    def wgs_has_subscription_configuration(self):
        self.ensure_one()
        return bool(
            self.wgs_participant_ids_json
            or self.wgs_subscription_plan_id
            or self.wgs_subscription_pricing_id
            or self.wgs_subscription_start_date
            or self.wgs_subscription_end_date
            or self.wgs_subscription_source_id
            or self.wgs_subscription_pending_move_id
            or self.wgs_subscription_refund_origin_line_id
            or self.wgs_discount_code
        )


class PosOrder(models.Model):
    _inherit = 'pos.order'
    _WGS_INVALID_SUBSCRIPTION_STATE_TOKENS = (
        'cancel',
        'churn',
        'close',
        'draft',
        'pause',
        'upsell',
    )

    @api.model
    def _wgs_ensure_pos_user_for_pos(self, error_message):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise UserError(error_message)

    @api.model
    def _wgs_product_model_for_pos(self):
        return self.env['product.product'].sudo()

    @api.model
    def _wgs_get_pos_product_field_names(self, product):
        field_names = []
        session_model = self.env['pos.session'].sudo()
        loader_method = getattr(session_model, '_loader_params_product_product', None)
        if callable(loader_method):
            try:
                loader_params = loader_method()
            except Exception:
                loader_params = {}
            search_params = loader_params.get('search_params', {}) if isinstance(loader_params, dict) else {}
            for field_name in search_params.get('fields') or []:
                if field_name in product._fields and field_name not in field_names:
                    field_names.append(field_name)
        for field_name in (
            'name',
            'display_name',
            'default_code',
            'lst_price',
            'list_price',
            'sale_ok',
            'available_in_pos',
            'recurring_invoice',
            'is_subscription',
            'subscription_ok',
            'max_participants_total',
            'product_tmpl_id',
            'taxes_id',
            'uom_id',
            'pos_categ_ids',
            'categ_id',
            'company_id',
            'barcode',
            'description',
            'description_sale',
            'to_weight',
            'tracking',
            'write_date',
        ):
            if field_name in product._fields and field_name not in field_names:
                field_names.append(field_name)
        return field_names

    @api.model
    def _wgs_get_product_company_domain_for_pos(self, product_model=None, company=False):
        product_model = product_model or self.env['product.product']
        company = company or self.env.company
        if not company:
            return []
        if 'company_id' in product_model._fields:
            return ['|', ('company_id', '=', False), ('company_id', '=', company.id)]
        template_model = self.env['product.template']
        if 'company_id' in template_model._fields:
            return ['|', ('product_tmpl_id.company_id', '=', False), ('product_tmpl_id.company_id', '=', company.id)]
        return []

    @api.model
    def _wgs_partner_model_for_pos(self):
        return self.env['res.partner'].sudo().with_context(active_test=False)

    @api.model
    def _wgs_sale_order_model_for_pos(self):
        return self.env['sale.order'].sudo()

    @api.model
    def _wgs_browse_product_for_pos(self, product_id):
        try:
            product_id = int(product_id or 0)
        except (TypeError, ValueError):
            product_id = 0
        if product_id <= 0:
            return self.env['product.product']
        return self._wgs_product_model_for_pos().browse(product_id).exists()

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
    def _wgs_browse_source_subscription_for_pos(self, subscription_id):
        try:
            subscription_id = int(subscription_id or 0)
        except (TypeError, ValueError):
            subscription_id = 0
        if subscription_id <= 0:
            return self.env['sale.order']
        return self._wgs_sale_order_model_for_pos().browse(subscription_id).exists()

    @api.model
    def wgs_get_partner_directory_summary_for_pos(self):
        return self.env['sale.order'].get_partner_directory_summary_for_pos()

    @api.model
    def wgs_get_partner_directory_rows_for_pos(self, offset=0, limit=500, state_filter=False, search_term=False):
        return self.env['sale.order'].get_partner_directory_rows_for_pos(
            offset=offset,
            limit=limit,
            state_filter=state_filter,
            search_term=search_term,
        )

    @api.model
    def wgs_get_partner_directory_row_for_pos(self, partner_id):
        return self.env['sale.order'].get_partner_directory_row_for_pos(partner_id)

    @api.model
    def wgs_search_subscription_participants_for_pos(self, search_term=False, limit=120):
        return self.env['sale.order'].search_subscription_participants_for_pos(
            search_term=search_term,
            limit=limit,
        )

    @api.model
    def wgs_get_partner_subscription_detail_for_pos(self, partner_id):
        return self.env['sale.order'].get_partner_subscription_detail_for_pos(partner_id)

    @api.model
    def wgs_update_subscription_participants_for_pos(self, subscription_id, participant_ids):
        return self.env['sale.order'].wgs_update_subscription_participants_for_pos(subscription_id, participant_ids)

    @api.model
    def wgs_create_partner_for_pos(self, vals):
        return self.env['sale.order'].wgs_create_partner_for_pos(vals)

    @api.model
    def wgs_update_partner_curp_for_pos(self, partner_id, curp):
        return self.env['sale.order'].wgs_update_partner_curp_for_pos(partner_id, curp)

    @api.model
    def wgs_update_partner_for_pos(self, partner_id, vals):
        return self.env['sale.order'].wgs_update_partner_for_pos(partner_id, vals)

    @api.model
    def wgs_get_partner_record_for_pos(self, partner_id):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar clientes desde Punto de Venta.'))
        partner = self._wgs_browse_partner_for_pos(partner_id)
        if not partner:
            return {}

        field_names = []
        for field_name in (
            'name',
            'display_name',
            'email',
            'phone',
            'mobile',
            'barcode',
            'vat',
            'street',
            'street2',
            'zip',
            'city',
            'lang',
            'type',
            'is_company',
            'company_name',
            'parent_id',
            'country_id',
            'state_id',
            'write_date',
        ):
            if field_name in partner._fields:
                field_names.append(field_name)

        values = partner.read(field_names, load=False)[0] if field_names else {}
        values['id'] = partner.id
        if 'display_name' not in values:
            values['display_name'] = partner.display_name
        if 'name' not in values:
            values['name'] = partner.name
        return values

    @api.model
    def wgs_get_access_event_log_for_pos(self, options=False):
        return self.env['sale.order'].wgs_get_access_event_log_for_pos(options or {})

    @api.model
    def wgs_open_access_door_for_pos(self, device_id, options=False):
        return self.env['sale.order'].wgs_open_access_door_for_pos(device_id, options or {})

    @api.model
    def wgs_block_partner_access_for_pos(self, partner_id, reason):
        return self.env['sale.order'].wgs_block_partner_access_for_pos(partner_id, reason)

    @api.model
    def wgs_unblock_partner_access_for_pos(self, partner_id):
        return self.env['sale.order'].wgs_unblock_partner_access_for_pos(partner_id)

    @api.model
    def wgs_grant_external_access_for_pos(self, partner_id, provider, options=False):
        return self.env['sale.order'].wgs_grant_external_access_for_pos(partner_id, provider, options or {})

    @api.model
    def wgs_get_product_record_for_pos(self, product_id, company_id=False):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar productos desde Punto de Venta.'))
        product = self._wgs_browse_product_for_pos(product_id)
        if not product:
            return {}

        company = self.env['res.company'].sudo().browse(int(company_id or 0)).exists() if company_id else self.env.company
        if company:
            product_company = getattr(product, 'company_id', False) or getattr(product.product_tmpl_id, 'company_id', False)
            if product_company and product_company.id != company.id:
                return {}

        field_names = self._wgs_get_pos_product_field_names(product)
        values = product.read(field_names, load=False)[0] if field_names else {}
        values['id'] = product.id
        if 'display_name' not in values:
            values['display_name'] = product.display_name
        if 'name' not in values:
            values['name'] = product.name
        return values

    @api.model
    def wgs_validate_subscription_product_eligibility_for_pos(
        self,
        partner_id,
        product_id,
        flow='new',
        source_subscription_id=False,
    ):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para validar productos de suscripción desde Punto de Venta.'))

        partner = self._wgs_browse_partner_for_pos(partner_id)
        if not partner:
            return {
                'ok': False,
                'error_message': _('El cliente seleccionado no existe.'),
            }

        product = self._wgs_browse_product_for_pos(product_id)
        if not product:
            return {
                'ok': False,
                'error_message': _('El producto seleccionado no existe o no está disponible.'),
            }

        student_age_check_required = bool(getattr(product.product_tmpl_id, 'wgs_student_age_lock', False))
        free_trial_day = bool(getattr(product.product_tmpl_id, 'wgs_free_trial_day', False))
        normalized_flow = str(flow or 'new').strip().lower()
        if normalized_flow not in ('new', 'renewal', 'reenroll', 'upsale'):
            normalized_flow = 'new'

        if normalized_flow == 'new':
            blocking_subscription = self._wgs_get_blocking_subscription_for_new_flow(
                partner,
                company=self.env.company,
            )
            if blocking_subscription:
                return {
                    'ok': False,
                    'error_code': 'active_subscription_exists',
                    'error_message': self._wgs_get_blocking_subscription_for_new_flow_message(blocking_subscription),
                }
            reenroll_source = self._wgs_get_reenroll_source_for_new_same_product_flow(
                partner,
                product,
                company=self.env.company,
            )
            if reenroll_source:
                return {
                    'ok': False,
                    'error_code': 'reenroll_required_for_same_product',
                    'error_message': self._wgs_get_reenroll_required_for_new_same_product_message(
                        reenroll_source,
                        product,
                    ),
                }

        sale_order_model = self.env['sale.order'].sudo()
        curp = sale_order_model._get_partner_curp_for_pos(partner)
        if (student_age_check_required or free_trial_day) and not curp:
            return {
                'ok': False,
                'error_code': 'missing_curp',
                'error_message': _(
                    'Este producto requiere CURP para validar la operación antes de agregarlo al ticket.'
                ),
            }

        if free_trial_day and normalized_flow != 'new':
            return {
                'ok': False,
                'error_code': 'free_trial_invalid_flow',
                'error_message': _(
                    'El día de prueba gratis solo puede venderse como alta nueva.'
                ),
            }

        if free_trial_day and self._wgs_has_free_trial_usage_for_curp(curp):
            return {
                'ok': False,
                'error_code': 'free_trial_already_used',
                'error_message': _(
                    'La CURP %(curp)s ya utilizó previamente el día de prueba gratis. Solo se permite una vez en la vida.'
                ) % {'curp': curp},
            }

        birthdate = False
        age = 0
        if student_age_check_required:
            birthdate = self._wgs_get_birthdate_from_curp_for_pos(curp)
            if not birthdate:
                return {
                    'ok': False,
                    'error_code': 'invalid_curp',
                    'error_message': _(
                        'La CURP %(curp)s no tiene un formato válido para calcular la edad del titular.'
                    ) % {'curp': curp},
                }

            age = self._wgs_get_age_for_pos(birthdate)
            if age >= 26:
                return {
                    'ok': False,
                    'error_code': 'student_age_limit',
                    'error_message': _(
                        'El paquete %(product)s solo permite titulares menores de 26 años. '
                        '%(partner)s tiene %(age)s años según su CURP.'
                    ) % {
                        'product': product.display_name,
                        'partner': partner.display_name,
                        'age': age,
                    },
                }

        return {
            'ok': True,
            'student_age_lock': student_age_check_required,
            'free_trial_day': free_trial_day,
            'flow': normalized_flow,
            'source_subscription_id': int(source_subscription_id or 0) or False,
            'age': age,
            'curp': curp,
            'birthdate': fields.Date.to_string(birthdate) if birthdate else False,
        }

    @api.model
    def wgs_get_subscription_discount_offers_for_pos(self, partner_id, product_id, flow='new', source_subscription_id=False):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar descuentos de suscripción desde Punto de Venta.'))
        return []

    @api.model
    def wgs_authorize_subscription_discount_for_pos(
        self,
        partner_id,
        product_id,
        flow='new',
        discount_percent=0.0,
        supervisor_pin=False,
        source_subscription_id=False,
    ):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para autorizar descuentos desde Punto de Venta.'))

        partner = self._wgs_browse_partner_for_pos(partner_id)
        product = self._wgs_browse_product_for_pos(product_id)
        if not partner:
            return {
                'ok': False,
                'error_message': _('El cliente seleccionado no existe.'),
            }
        if not product:
            return {
                'ok': False,
                'error_message': _('El producto seleccionado no existe o no está disponible.'),
            }

        normalized_flow = str(flow or 'new').strip().lower()
        if normalized_flow not in ('new', 'upsale', 'renewal', 'reenroll'):
            return {
                'ok': False,
                'error_message': _('El flujo de venta no permite autorizar descuentos de membresía.'),
            }

        percent = self._wgs_to_float(discount_percent)
        if percent <= 0.0 or percent > 100.0:
            return {
                'ok': False,
                'error_message': _('Captura un porcentaje de descuento mayor a 0 y menor o igual a 100.'),
            }

        authorizer = self._wgs_find_discount_authorizer_for_pos(supervisor_pin)
        if not authorizer:
            return {
                'ok': False,
                'error_message': _('El PIN WGS de autorización no es válido.'),
            }

        authorized_at = fields.Datetime.now()
        label = _('Descuento autorizado (%s%%)') % ('%g' % percent)
        return {
            'ok': True,
            'code': 'manual_percent',
            'label': label,
            'discount_percent': percent,
            'discount_fixed_amount': 0.0,
            'authorized_employee_id': authorizer.id,
            'authorized_by': authorizer.display_name,
            'authorized_at': fields.Datetime.to_string(authorized_at),
            'birthday_year': 0,
        }

    @api.model
    def wgs_update_partner_photo_for_pos(self, partner_id, image_1920):
        return self.env['sale.order'].wgs_update_partner_photo_for_pos(partner_id, image_1920)

    @api.model
    def wgs_resync_subscription_access_for_pos(self, subscription_id):
        return self.env['sale.order'].wgs_resync_subscription_access_for_pos(subscription_id)

    @api.model
    def _wgs_get_birthdate_from_curp_for_pos(self, curp):
        partner_model = self._wgs_partner_model_for_pos()
        normalized = partner_model._wgs_normalize_curp(curp) if hasattr(partner_model, '_wgs_normalize_curp') else False
        if not normalized or len(normalized) != 18:
            return False

        try:
            year = int(normalized[4:6])
            month = int(normalized[6:8])
            day = int(normalized[8:10])
        except (TypeError, ValueError):
            return False

        current_two_digit_year = fields.Date.context_today(self).year % 100
        century = 2000 if year <= current_two_digit_year else 1900
        try:
            return date(century + year, month, day)
        except ValueError:
            return False

    @api.model
    def _wgs_get_age_for_pos(self, birthdate, today=False):
        if not birthdate:
            return 0
        birthdate = fields.Date.to_date(birthdate)
        today = fields.Date.to_date(today) if today else fields.Date.context_today(self)
        age = today.year - birthdate.year
        if (today.month, today.day) < (birthdate.month, birthdate.day):
            age -= 1
        return max(age, 0)

    @api.model
    def _wgs_find_discount_authorizer_for_pos(self, supervisor_pin):
        pin = str(supervisor_pin or '').strip()
        if not pin:
            return self.env['hr.employee']
        Employee = self.env['hr.employee'].sudo().with_context(active_test=False)
        if not hasattr(Employee, '_wgs_find_by_authorization_pin'):
            return self.env['hr.employee']
        return Employee._wgs_find_by_authorization_pin(pin)

    @api.model
    def _wgs_has_free_trial_usage_for_curp(self, curp):
        sale_order_model = self.env['sale.order'].sudo()
        partner_model = self._wgs_partner_model_for_pos()
        normalized = sale_order_model._wgs_normalize_partner_curp_for_pos(curp)
        if not normalized:
            return False

        curp_field = sale_order_model._wgs_get_partner_curp_field_for_pos(partner_model)
        if not curp_field:
            return False
        sale_line_model = self.env['sale.order.line'].sudo()
        sale_domain = [
            ('order_id.partner_id.%s' % curp_field, '=', normalized),
            ('product_id.product_tmpl_id.wgs_free_trial_day', '=', True),
        ]
        if sale_line_model.search_count(sale_domain):
            return True

        pos_line_model = self.env['pos.order.line'].sudo()
        pos_domain = [
            ('order_id.partner_id.%s' % curp_field, '=', normalized),
            ('product_id.product_tmpl_id.wgs_free_trial_day', '=', True),
            ('order_id.state', 'not in', ('draft', 'cancel')),
        ]
        return bool(pos_line_model.search_count(pos_domain))

    @api.model
    def _wgs_product_has_single_day_term(self, product):
        product = product.exists() if hasattr(product, 'exists') else product
        if not product:
            return False
        tmpl = product.product_tmpl_id if getattr(product, 'product_tmpl_id', False) else product
        return bool(
            getattr(tmpl, 'wgs_single_day_access', False)
            or getattr(tmpl, 'wgs_free_trial_day', False)
        )

    @api.model
    def _wgs_is_subscription_buffer_ready(self):
        model_name = 'wgs.pos.subscription.buffer'
        if model_name not in self.env.registry:
            return False

        # Avoid hard failures when code is deployed before module upgrade creates the SQL table.
        table_name = self.env[model_name]._table
        try:
            self.env.cr.execute("SELECT to_regclass(%s)", (table_name,))
            row = self.env.cr.fetchone()
        except Exception as error:
            _logger.warning(
                'WGS POS: subscription buffer readiness check failed for table %s (%s)',
                table_name,
                error,
            )
            return False
        return bool(row and row[0])

    @api.model
    def wgs_stage_subscription_config_for_uuid(self, order_uuid, configs):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para guardar configuración de suscripción desde Punto de Venta.'))

        order_uuid = (order_uuid or '').strip()
        if not order_uuid:
            return {'ok': False, 'reason': 'missing_uuid'}

        if not isinstance(configs, list):
            configs = []
        if not self._wgs_is_subscription_buffer_ready():
            _logger.warning(
                'WGS POS: subscription buffer table is not ready yet. Skipping stage for uuid=%s',
                order_uuid,
            )
            return {'ok': False, 'reason': 'buffer_not_ready'}

        try:
            buffer_model = self.env['wgs.pos.subscription.buffer'].sudo()
            existing = buffer_model.search([('order_uuid', '=', order_uuid)], limit=1, order='id desc')
            if not configs:
                if existing:
                    existing.unlink()
                return {'ok': True, 'cleared': True}

            payload_json = json.dumps(configs)
            if existing:
                existing.write({'payload_json': payload_json})
            else:
                buffer_model.create({'order_uuid': order_uuid, 'payload_json': payload_json})
        except Exception as error:
            _logger.warning(
                'WGS POS: could not stage subscription buffer for uuid=%s (%s)',
                order_uuid,
                error,
            )
            return {'ok': False, 'reason': 'buffer_error'}
        return {'ok': True}

    def _wgs_get_subscription_product_flags_for_pos(self, product):
        product.ensure_one()
        student_age_lock = bool(getattr(product.product_tmpl_id, 'wgs_student_age_lock', False))
        family_authorization = bool(getattr(product.product_tmpl_id, 'wgs_requires_family_authorization', False))
        single_day_access = bool(getattr(product.product_tmpl_id, 'wgs_single_day_access', False))
        free_trial_day = bool(getattr(product.product_tmpl_id, 'wgs_free_trial_day', False))
        requires_curp = bool(
            getattr(product.product_tmpl_id, 'wgs_requires_curp', False)
            or student_age_lock
            or free_trial_day
        )
        max_total = int(product.max_participants_total or 1)
        if max_total < 1:
            max_total = 1
        return {
            'max_participants_total': max_total,
            'requires_curp': requires_curp,
            'student_age_lock': student_age_lock,
            'family_authorization': family_authorization,
            'single_day_access': single_day_access,
            'free_trial_day': free_trial_day,
        }

    def _wgs_build_product_pricing_payload_for_pos(
        self,
        product,
        *,
        flow='new',
        partner=False,
        source_order=False,
        fallback=0.0,
        preferred_plan_id=False,
        preferred_pricing_id=False,
        start_date=False,
    ):
        product.ensure_one()
        source_order = source_order.exists() if source_order else self.env['sale.order']
        pricing_company = source_order.company_id if source_order and 'company_id' in source_order._fields else False
        pricing_fiscal_position = source_order.fiscal_position_id if source_order and 'fiscal_position_id' in source_order._fields else False
        snapshot = self._wgs_resolve_subscription_pricing_snapshot(
            flow=flow,
            product=product,
            partner=partner,
            source_order=source_order,
            company=pricing_company,
            fiscal_position=pricing_fiscal_position,
            fallback=fallback,
            preferred_plan_id=preferred_plan_id,
            preferred_pricing_id=preferred_pricing_id,
            include_credit=bool(source_order),
            start_date=start_date,
        )
        candidates = list(snapshot.get('candidates') or [])
        candidates.sort(key=lambda row: (row['sequence'], row.get('pricing_id') or 0))
        flags = self._wgs_get_subscription_product_flags_for_pos(product)
        return {
            **flags,
            'charge_now': float(snapshot.get('charge_now') or 0.0),
            'credit_amount': float(snapshot.get('credit_amount') or 0.0),
            'recurring_price': float(snapshot.get('price_unit') or 0.0),
            'ticket_charge_now': float(snapshot.get('ticket_charge_now') or 0.0),
            'ticket_credit_amount': float(snapshot.get('ticket_credit_amount') or 0.0),
            'ticket_recurring_price': float(snapshot.get('ticket_price_unit') or 0.0),
            'display_charge_now': float(snapshot.get('display_charge_now') or 0.0),
            'display_credit_amount': float(snapshot.get('display_credit_amount') or 0.0),
            'display_recurring_price': float(snapshot.get('display_price_unit') or 0.0),
            'subscription_start_date': snapshot.get('subscription_start_date') or False,
            'subscription_end_date': snapshot.get('subscription_end_date') or False,
            'next_billing_date': snapshot.get('next_billing_date') or False,
            'first_period_alignment': bool(snapshot.get('first_period_alignment')),
            'first_period_start_date': snapshot.get('first_period_start_date') or False,
            'first_period_access_start_date': snapshot.get('first_period_access_start_date') or False,
            'first_period_days': int(snapshot.get('first_period_days') or 0),
            'first_period_charge_days': int(snapshot.get('first_period_charge_days') or 0),
            'source_recurring_price': float(snapshot.get('source_recurring_price') or 0.0),
            'source_display_recurring_price': float(snapshot.get('source_display_recurring_price') or 0.0),
            'default_plan_id': snapshot.get('plan_id') or False,
            'plan_id': snapshot.get('plan_id') or False,
            'plan_name': snapshot.get('plan_name') or False,
            'default_pricing_id': snapshot.get('pricing_id') or False,
            'pricing_id': snapshot.get('pricing_id') or False,
            'default_price': float(snapshot.get('price_unit') or 0.0),
            'default_display_price': float(snapshot.get('display_price_unit') or 0.0),
            'interval_label': snapshot.get('interval_label') or '',
            'interval_value': int(snapshot.get('interval_value') or 1),
            'interval_unit': snapshot.get('interval_unit') or 'month',
            'is_upgrade': bool(source_order),
            'source_subscription_id': source_order.id if source_order else False,
            'source_subscription_name': source_order.name if source_order else False,
            'plans': [
                {
                    'plan_id': row.get('plan_id') or False,
                    'plan_name': row.get('plan_name') or _('Plan recurrente'),
                    'pricing_id': row.get('pricing_id') or False,
                    'price': float(row.get('price') or 0.0),
                    'display_price': float(
                        self._wgs_get_price_with_taxes_for_pos(
                            product,
                            row.get('price') or 0.0,
                            partner=partner or False,
                            company=pricing_company or False,
                            fiscal_position=pricing_fiscal_position or False,
                        )
                    ),
                    'interval_label': row.get('interval_label') or '',
                    'interval_value': int(row.get('interval_value') or 1),
                    'interval_unit': row.get('interval_unit') or 'month',
                }
                for row in candidates
            ],
        }

    def _wgs_prepare_subscription_pricing_request_for_pos(
        self,
        *,
        partner_id=False,
        product_id=False,
        flow='new',
        source_subscription_id=False,
        pending_move_id=False,
    ):
        normalized_flow = str(flow or 'new').strip().lower()
        if normalized_flow not in ('new', 'upsale', 'renewal', 'reenroll'):
            normalized_flow = 'new'

        partner = self._wgs_browse_partner_for_pos(partner_id) if partner_id else self.env['res.partner']
        product = self._wgs_browse_product_for_pos(product_id) if product_id else self.env['product.product']
        source_order = self.env['sale.order']

        if normalized_flow == 'new':
            if not product:
                raise UserError(_('El producto seleccionado no existe o no está disponible.'))
            if partner:
                blocking_subscription = self._wgs_get_blocking_subscription_for_new_flow(
                    partner,
                    company=self.env.company,
                )
                if blocking_subscription:
                    raise UserError(
                        self._wgs_get_blocking_subscription_for_new_flow_message(blocking_subscription)
                    )
                reenroll_source = self._wgs_get_reenroll_source_for_new_same_product_flow(
                    partner,
                    product,
                    company=self.env.company,
                )
                if reenroll_source:
                    raise UserError(
                        self._wgs_get_reenroll_required_for_new_same_product_message(
                            reenroll_source,
                            product,
                        )
                    )

        elif normalized_flow == 'upsale':
            source_order = self._wgs_browse_source_subscription_for_pos(source_subscription_id)
            if not source_order:
                raise UserError(_('La suscripción origen no existe.'))
            if not self._wgs_order_has_subscription_signal(source_order):
                raise UserError(_('La orden origen no corresponde a una suscripción válida.'))
            if not self._wgs_is_subscription_order_active_for_upsell(source_order):
                raise UserError(_('La suscripción origen no está activa para upsale.'))
            if not product:
                raise UserError(_('El producto seleccionado no existe o no está disponible.'))
            if not partner and 'partner_id' in source_order._fields:
                partner = source_order.partner_id

        elif normalized_flow == 'renewal':
            source_order = self._wgs_browse_source_subscription_for_pos(source_subscription_id)
            if not source_order:
                raise UserError(_('La suscripción origen no existe.'))
            if not self._wgs_order_has_subscription_signal(source_order):
                raise UserError(_('La orden origen no corresponde a una suscripción válida.'))
            if not self._wgs_is_subscription_order_active_for_upsell(source_order):
                raise UserError(_('La suscripción origen no está activa para renovación.'))

        elif normalized_flow == 'reenroll':
            source_order = self._wgs_browse_source_subscription_for_pos(source_subscription_id)
            if not source_order:
                raise UserError(_('La suscripción origen no existe.'))
            if not self._wgs_order_has_subscription_signal(source_order):
                raise UserError(_('La orden origen no corresponde a una suscripción válida.'))
            if not self._wgs_is_subscription_order_closed_for_reenroll(source_order):
                raise UserError(_('La suscripción origen no está cerrada ni cancelada para reinscripción.'))

        return {
            'flow': normalized_flow,
            'partner': partner if partner else False,
            'product': product if product else False,
            'source_order': source_order if source_order else False,
        }

    def _wgs_build_subscription_quote_payload_for_pos(
        self,
        *,
        partner_id=False,
        product_id=False,
        flow='new',
        source_subscription_id=False,
        pending_move_id=False,
        fallback=0.0,
        preferred_plan_id=False,
        preferred_pricing_id=False,
        include_offers=False,
        start_date=False,
    ):
        request_data = self._wgs_prepare_subscription_pricing_request_for_pos(
            partner_id=partner_id,
            product_id=product_id,
            flow=flow,
            source_subscription_id=source_subscription_id,
            pending_move_id=pending_move_id,
        )
        normalized_flow = request_data['flow']
        partner = request_data['partner']
        product = request_data['product']
        source_order = request_data['source_order']
        offers = []

        if normalized_flow in ('new', 'upsale'):
            pricing = self._wgs_build_product_pricing_payload_for_pos(
                product=product,
                flow=normalized_flow,
                partner=partner if partner else False,
                source_order=source_order if source_order else False,
                fallback=fallback,
                preferred_plan_id=preferred_plan_id,
                preferred_pricing_id=preferred_pricing_id,
                start_date=start_date,
            )
            pricing['flow'] = normalized_flow
            pricing['is_upgrade'] = bool(source_order) if normalized_flow == 'upsale' else False
            pricing['is_renewal'] = False
        elif normalized_flow in ('renewal', 'reenroll'):
            pricing = self._wgs_build_subscription_recurring_charge_payload(
                source_order,
                product_id=product.id if product else False,
                preferred_plan_id=preferred_plan_id,
                preferred_pricing_id=preferred_pricing_id,
                is_renewal=normalized_flow == 'renewal',
                is_reenroll=normalized_flow == 'reenroll',
            )
            pricing['flow'] = normalized_flow
        else:
            raise UserError(_('No se pudo resolver el flujo de pricing solicitado.'))

        return {
            'flow': normalized_flow,
            'pricing': pricing,
            'offers': offers,
        }

    @api.model
    def wgs_get_subscription_pricing_for_pos(
        self,
        partner_id=False,
        product_id=False,
        flow='new',
        source_subscription_id=False,
        pending_move_id=False,
        fallback=0.0,
        preferred_plan_id=False,
        preferred_pricing_id=False,
        start_date=False,
    ):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar pricing de suscripción desde Punto de Venta.'))
        return self._wgs_build_subscription_quote_payload_for_pos(
            partner_id=partner_id,
            product_id=product_id,
            flow=flow,
            source_subscription_id=source_subscription_id,
            pending_move_id=pending_move_id,
            fallback=fallback,
            preferred_plan_id=preferred_plan_id,
            preferred_pricing_id=preferred_pricing_id,
            include_offers=False,
            start_date=start_date,
        )['pricing']

    @api.model
    def wgs_get_subscription_quote_for_pos(
        self,
        partner_id=False,
        product_id=False,
        flow='new',
        source_subscription_id=False,
        pending_move_id=False,
        fallback=0.0,
        preferred_plan_id=False,
        preferred_pricing_id=False,
        start_date=False,
    ):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar cotizaciones de suscripción desde Punto de Venta.'))
        return self._wgs_build_subscription_quote_payload_for_pos(
            partner_id=partner_id,
            product_id=product_id,
            flow=flow,
            source_subscription_id=source_subscription_id,
            pending_move_id=pending_move_id,
            fallback=fallback,
            preferred_plan_id=preferred_plan_id,
            preferred_pricing_id=preferred_pricing_id,
            include_offers=True,
            start_date=start_date,
        )

    @api.model
    def wgs_get_subscription_cancellation_refund_for_pos(self, subscription_id):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar cancelación de suscripción desde Punto de Venta.'))

        try:
            subscription_id = int(subscription_id or 0)
        except (TypeError, ValueError):
            subscription_id = 0
        source_order = self._wgs_browse_source_subscription_for_pos(subscription_id)
        if not source_order:
            raise UserError(_('La suscripción origen no existe.'))
        if not self._wgs_order_has_subscription_signal(source_order):
            raise UserError(_('La orden origen no corresponde a una suscripción válida.'))

        origin_line = self._wgs_get_refundable_pos_line_for_subscription(source_order)
        if not origin_line:
            raise UserError(_('No se encontró un cobro POS devoluble ligado exactamente a esta suscripción.'))

        refund_total = self._wgs_get_pos_line_total_amount(origin_line, include_taxes=True)
        if refund_total <= 0.0:
            refund_total = abs(float(origin_line.price_unit or 0.0) * float(origin_line.qty or 0.0))

        return {
            'subscription_id': source_order.id,
            'subscription_name': source_order.name,
            'origin_pos_line_id': origin_line.id,
            'origin_pos_order_id': origin_line.order_id.id,
            'origin_pos_order_name': origin_line.order_id.pos_reference or origin_line.order_id.name or False,
            'origin_date': fields.Datetime.to_string(origin_line.order_id.date_order) if getattr(origin_line.order_id, 'date_order', False) else False,
            'product_id': origin_line.product_id.id,
            'product_name': origin_line.product_id.display_name,
            'qty': abs(float(origin_line.qty or 0.0)),
            'price_unit': abs(float(origin_line.price_unit or 0.0)),
            'discount': float(origin_line.discount or 0.0) if 'discount' in origin_line._fields else 0.0,
            'amount_total': round(max(refund_total, 0.0), 2),
        }

    @api.model
    def wgs_get_subscription_product_catalog_for_pos(self, search_term=False, limit=80, company_id=False):
        self._wgs_ensure_pos_user_for_pos(_('No tienes permisos para consultar productos de suscripción desde Punto de Venta.'))

        product_model = self._wgs_product_model_for_pos()
        company = self.env['res.company'].sudo().browse(int(company_id or 0)).exists() if company_id else self.env.company
        domain = [('sale_ok', '=', True)]
        if 'active' in product_model._fields:
            domain.append(('active', '=', True))
        recurring_domain = ['|', ('recurring_invoice', '=', True), ('product_tmpl_id.recurring_invoice', '=', True)]
        domain = domain + recurring_domain
        domain += self._wgs_get_product_company_domain_for_pos(product_model, company=company)

        search_term = (search_term or '').strip()
        if search_term:
            domain += ['|', ('display_name', 'ilike', search_term), ('default_code', 'ilike', search_term)]

        try:
            limit = max(1, int(limit or 80))
        except (TypeError, ValueError):
            limit = 80
        products = product_model.search(domain, order='name asc, id asc', limit=limit)
        output = []
        for product in products:
            flags = self._wgs_get_subscription_product_flags_for_pos(product)
            output.append({
                'id': product.id,
                'name': product.display_name,
                'default_code': product.default_code or False,
                **flags,
                'default_plan_id': False,
                'default_pricing_id': False,
                'default_price': 0.0,
                'default_display_price': 0.0,
                'plans': [],
            })
        return output

    @api.model
    def _order_line_fields(self, line, session_id=None):
        values = super()._order_line_fields(line, session_id=session_id)
        ui_line = self._wgs_extract_ui_line_payload(line)
        config_payload = self._wgs_extract_subscription_config_payload(ui_line)
        has_subscription_config = self._wgs_has_subscription_line_config_payload(config_payload)

        participant_ids = config_payload.get('participant_ids')
        if isinstance(participant_ids, list):
            cleaned = []
            for value in participant_ids:
                try:
                    participant_id = int(value)
                except (TypeError, ValueError):
                    continue
                if participant_id > 0:
                    cleaned.append(participant_id)
            values['wgs_participant_ids_json'] = json.dumps(list(dict.fromkeys(cleaned)))

        pricing_snapshot = config_payload.get('pricing_snapshot')
        if isinstance(pricing_snapshot, dict):
            values['wgs_pricing_snapshot_json'] = json.dumps(pricing_snapshot)

        for field_name in ('wgs_subscription_plan_id', 'wgs_subscription_pricing_id'):
            if field_name == 'wgs_subscription_plan_id':
                value = config_payload.get('plan_id')
            else:
                value = config_payload.get('pricing_id')
            try:
                int_value = int(value)
            except (TypeError, ValueError):
                int_value = 0
            if int_value > 0:
                values[field_name] = int_value

        raw_end_date = config_payload.get('end_date')
        if raw_end_date:
            end_date = fields.Date.to_date(raw_end_date)
            if end_date:
                values['wgs_subscription_end_date'] = end_date
        raw_start_date = config_payload.get('start_date')
        if raw_start_date:
            start_date = fields.Date.to_date(raw_start_date)
            if start_date:
                values['wgs_subscription_start_date'] = start_date

        flow_value = str(config_payload.get('flow') or 'new').strip().lower()
        values['wgs_subscription_flow'] = flow_value if flow_value in ('renewal', 'reenroll', 'upsale', 'pending_charge', 'cancellation_refund') else 'new'

        source_subscription_id = self._wgs_to_int(config_payload.get('source_subscription_id'))
        if source_subscription_id > 0:
            values['wgs_subscription_source_id'] = source_subscription_id
        pending_move_id = self._wgs_to_int(config_payload.get('pending_move_id'))
        if pending_move_id > 0:
            values['wgs_subscription_pending_move_id'] = pending_move_id
        refund_origin_line_id = self._wgs_to_int(config_payload.get('refund_origin_line_id'))
        if refund_origin_line_id > 0:
            values['wgs_subscription_refund_origin_line_id'] = refund_origin_line_id

        discount_percent = self._wgs_to_float(config_payload.get('discount_percent'))
        if discount_percent > 0:
            values['wgs_discount_percent'] = discount_percent
        discount_fixed_amount = self._wgs_to_float(config_payload.get('discount_fixed_amount'))
        if discount_fixed_amount > 0:
            values['wgs_discount_fixed_amount'] = discount_fixed_amount
        discount_code = str(config_payload.get('discount_code') or '').strip()
        if discount_code:
            values['wgs_discount_code'] = discount_code
        discount_label = str(config_payload.get('discount_label') or '').strip()
        if discount_label:
            values['wgs_discount_label'] = discount_label
        authorized_employee_id = self._wgs_to_int(config_payload.get('discount_authorized_employee_id'))
        if authorized_employee_id > 0:
            values['wgs_discount_authorized_employee_id'] = authorized_employee_id
        authorized_by = str(config_payload.get('discount_authorized_by') or '').strip()
        if authorized_by:
            values['wgs_discount_authorized_by'] = authorized_by
        authorized_at = fields.Datetime.to_datetime(config_payload.get('discount_authorized_at'))
        if authorized_at:
            values['wgs_discount_authorized_at'] = fields.Datetime.to_string(authorized_at)
        birthday_year = self._wgs_to_int(config_payload.get('discount_birthday_year'))
        if birthday_year > 0:
            values['wgs_discount_birthday_year'] = birthday_year

        if has_subscription_config:
            locked_values = self._wgs_get_locked_subscription_line_price_values_for_pos(
                config_payload,
                fallback_price=values.get('price_unit'),
            )
            if locked_values.get('price_unit') is not False and 'price_unit' in values:
                values['price_unit'] = locked_values['price_unit']
            if 'discount' in values:
                values['discount'] = locked_values['discount']
        elif 'discount' in values:
            values['discount'] = 0

        return values

    @api.model
    def _wgs_has_subscription_line_config_payload(self, config_payload):
        if not isinstance(config_payload, dict):
            return False
        pricing_snapshot = config_payload.get('pricing_snapshot')
        if isinstance(pricing_snapshot, dict) and pricing_snapshot:
            return True
        participant_ids = config_payload.get('participant_ids')
        if isinstance(participant_ids, list) and participant_ids:
            return True
        for key in (
            'plan_id',
            'pricing_id',
            'start_date',
            'end_date',
            'source_subscription_id',
            'pending_move_id',
            'refund_origin_line_id',
            'discount_code',
            'discount_authorized_employee_id',
            'pricing_lock',
        ):
            if config_payload.get(key):
                return True
        return False

    @api.model
    def _wgs_get_locked_subscription_line_price_values_for_pos(self, config_payload, fallback_price=False):
        config_payload = config_payload if isinstance(config_payload, dict) else {}
        snapshot = config_payload.get('pricing_snapshot')
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        lock_payload = config_payload.get('pricing_lock') or config_payload.get('pricingLock')
        lock_payload = lock_payload if isinstance(lock_payload, dict) else {}

        price_unit = False
        for key in (
            'ticket_charge_now',
            'charge_now',
            'ticket_amount_total',
            'amount_total',
            'ticket_price_unit',
            'price_unit',
            'ticket_recurring_price',
            'recurring_price',
        ):
            if key in snapshot and snapshot.get(key) not in (None, ''):
                price_unit = self._wgs_to_signed_float(snapshot.get(key))
                break
        if price_unit is False and lock_payload:
            price_unit = self._wgs_to_signed_float(
                lock_payload.get('price_unit', lock_payload.get('priceUnit', False))
            )
        if price_unit is False and fallback_price is not False:
            price_unit = self._wgs_to_signed_float(fallback_price)

        discount = self._wgs_to_float(config_payload.get('discount_percent'))
        has_wgs_discount_authorization = bool(
            discount > 0.0
            and str(config_payload.get('discount_code') or '').strip()
            and self._wgs_to_int(config_payload.get('discount_authorized_employee_id')) > 0
            and config_payload.get('discount_authorized_at')
        )
        return {
            'price_unit': price_unit,
            'discount': discount if has_wgs_discount_authorization else 0.0,
        }

    @api.model
    def _wgs_extract_ui_line_payload(self, line):
        payload = {}

        def _collect(node, depth=0):
            if depth > 5:
                return
            if isinstance(node, dict):
                payload.update(node)
                for value in node.values():
                    _collect(value, depth + 1)
            elif isinstance(node, (list, tuple)):
                for value in node:
                    _collect(value, depth + 1)

        _collect(line)
        return payload

    @api.model
    def _wgs_extract_subscription_config_payload(self, ui_line):
        data = {
            'participant_ids': [],
            'pricing_snapshot': False,
            'plan_id': False,
            'pricing_id': False,
            'start_date': False,
            'end_date': False,
            'flow': 'new',
            'source_subscription_id': False,
            'pending_move_id': False,
            'refund_origin_line_id': False,
            'discount_code': False,
            'discount_label': False,
            'discount_percent': 0.0,
            'discount_fixed_amount': 0.0,
            'discount_authorized_employee_id': False,
            'discount_authorized_by': False,
            'discount_authorized_at': False,
            'discount_birthday_year': False,
            'pricing_lock': False,
        }
        if not isinstance(ui_line, dict):
            return data

        raw_config = ui_line.get('wgs_subscription_config') or ui_line.get('wgsSubscriptionConfig')
        if isinstance(raw_config, str):
            try:
                raw_config = json.loads(raw_config)
            except (TypeError, ValueError):
                raw_config = {}
        if not isinstance(raw_config, dict):
            raw_config = {}

        pricing_snapshot = raw_config.get('pricing_snapshot') or raw_config.get('pricingSnapshot') or False
        if isinstance(pricing_snapshot, str):
            try:
                pricing_snapshot = json.loads(pricing_snapshot)
            except (TypeError, ValueError):
                pricing_snapshot = False
        if isinstance(pricing_snapshot, dict):
            data['pricing_snapshot'] = pricing_snapshot

        pricing_lock = (
            ui_line.get('pricing_lock')
            or ui_line.get('pricingLock')
            or raw_config.get('pricing_lock')
            or raw_config.get('pricingLock')
            or False
        )
        if isinstance(pricing_lock, str):
            try:
                pricing_lock = json.loads(pricing_lock)
            except (TypeError, ValueError):
                pricing_lock = False
        if isinstance(pricing_lock, dict):
            data['pricing_lock'] = pricing_lock

        participant_raw = (
            ui_line.get('wgs_participant_ids')
            or ui_line.get('wgsParticipantIds')
            or raw_config.get('participant_ids')
            or raw_config.get('participantIds')
            or []
        )
        if isinstance(participant_raw, str):
            try:
                participant_raw = json.loads(participant_raw)
            except (TypeError, ValueError):
                participant_raw = []
        if isinstance(participant_raw, list):
            data['participant_ids'] = participant_raw

        data['plan_id'] = (
            ui_line.get('wgs_subscription_plan_id')
            or ui_line.get('wgsSubscriptionPlanId')
            or raw_config.get('plan_id')
            or raw_config.get('planId')
            or False
        )
        data['pricing_id'] = (
            ui_line.get('wgs_subscription_pricing_id')
            or ui_line.get('wgsSubscriptionPricingId')
            or raw_config.get('pricing_id')
            or raw_config.get('pricingId')
            or False
        )
        data['end_date'] = (
            ui_line.get('wgs_subscription_end_date')
            or ui_line.get('wgsSubscriptionEndDate')
            or raw_config.get('end_date')
            or raw_config.get('endDate')
            or False
        )
        data['start_date'] = (
            ui_line.get('wgs_subscription_start_date')
            or ui_line.get('wgsSubscriptionStartDate')
            or raw_config.get('start_date')
            or raw_config.get('startDate')
            or False
        )
        data['flow'] = (
            ui_line.get('wgs_subscription_flow')
            or ui_line.get('wgsSubscriptionFlow')
            or raw_config.get('flow')
            or raw_config.get('subscription_flow')
            or 'new'
        )
        data['source_subscription_id'] = (
            ui_line.get('wgs_subscription_source_id')
            or ui_line.get('wgsSubscriptionSourceId')
            or raw_config.get('source_subscription_id')
            or raw_config.get('sourceSubscriptionId')
            or False
        )
        data['pending_move_id'] = (
            ui_line.get('wgs_subscription_pending_move_id')
            or ui_line.get('wgsSubscriptionPendingMoveId')
            or raw_config.get('pending_move_id')
            or raw_config.get('pendingMoveId')
            or False
        )
        data['refund_origin_line_id'] = (
            ui_line.get('wgs_subscription_refund_origin_line_id')
            or ui_line.get('wgsSubscriptionRefundOriginLineId')
            or raw_config.get('refund_origin_line_id')
            or raw_config.get('refundOriginLineId')
            or False
        )
        data['discount_code'] = (
            ui_line.get('wgs_discount_code')
            or ui_line.get('wgsDiscountCode')
            or raw_config.get('discount_code')
            or raw_config.get('discountCode')
            or False
        )
        data['discount_label'] = (
            ui_line.get('wgs_discount_label')
            or ui_line.get('wgsDiscountLabel')
            or raw_config.get('discount_label')
            or raw_config.get('discountLabel')
            or False
        )
        data['discount_percent'] = (
            ui_line.get('wgs_discount_percent')
            or ui_line.get('wgsDiscountPercent')
            or raw_config.get('discount_percent')
            or raw_config.get('discountPercent')
            or 0.0
        )
        data['discount_fixed_amount'] = (
            ui_line.get('wgs_discount_fixed_amount')
            or ui_line.get('wgsDiscountFixedAmount')
            or raw_config.get('discount_fixed_amount')
            or raw_config.get('discountFixedAmount')
            or 0.0
        )
        data['discount_authorized_employee_id'] = (
            ui_line.get('wgs_discount_authorized_employee_id')
            or ui_line.get('wgsDiscountAuthorizedEmployeeId')
            or raw_config.get('discount_authorized_employee_id')
            or raw_config.get('discountAuthorizedEmployeeId')
            or False
        )
        data['discount_authorized_by'] = (
            ui_line.get('wgs_discount_authorized_by')
            or ui_line.get('wgsDiscountAuthorizedBy')
            or raw_config.get('discount_authorized_by')
            or raw_config.get('discountAuthorizedBy')
            or False
        )
        data['discount_authorized_at'] = (
            ui_line.get('wgs_discount_authorized_at')
            or ui_line.get('wgsDiscountAuthorizedAt')
            or raw_config.get('discount_authorized_at')
            or raw_config.get('discountAuthorizedAt')
            or False
        )
        data['discount_birthday_year'] = (
            ui_line.get('wgs_discount_birthday_year')
            or ui_line.get('wgsDiscountBirthdayYear')
            or raw_config.get('discount_birthday_year')
            or raw_config.get('discountBirthdayYear')
            or False
        )

        return data

    @api.model
    def _process_order(self, order, draft, *args, **kwargs):
        existing_order = kwargs.get('existing_order', False)
        if args:
            existing_order = args[0]
        super_process_order = super()._process_order
        try:
            pos_order_id = super_process_order(order, draft, existing_order)
        except TypeError as error:
            # Keep compatibility with Odoo variants where _process_order only accepts (order, draft).
            if '_process_order' in str(error) and 'positional arguments' in str(error):
                pos_order_id = super_process_order(order, draft)
            else:
                raise
        pos_order = self.browse(pos_order_id)

        if draft:
            return pos_order_id

        order_uuid = self._wgs_extract_order_uuid(order)
        ui_configs = pos_order._wgs_extract_ui_subscription_line_configs(order)
        if not ui_configs and order_uuid:
            ui_configs = pos_order._wgs_get_buffered_subscription_configs(order_uuid)

        if ui_configs:
            pos_order._wgs_apply_subscription_line_configs(ui_configs)
        else:
            pos_order._wgs_apply_ui_subscription_line_config(order)
        pos_order._wgs_align_partner_from_subscription_lines()
        pos_order._wgs_sync_subscription_sales()
        return pos_order_id

    @api.model
    def _wgs_extract_order_uuid(self, ui_order):
        if not isinstance(ui_order, dict):
            return False
        for key in ('uuid', 'uid', 'order_uuid', 'orderUid'):
            value = ui_order.get(key)
            if value:
                return str(value).strip()
        return False

    def _wgs_get_buffered_subscription_configs(self, order_uuid):
        order_uuid = (order_uuid or '').strip()
        if not order_uuid:
            return []
        if not self._wgs_is_subscription_buffer_ready():
            return []

        try:
            buffer_model = self.env['wgs.pos.subscription.buffer'].sudo()
            buffer_record = buffer_model.search([('order_uuid', '=', order_uuid)], limit=1, order='id desc')
            if not buffer_record:
                return []
            try:
                payload = json.loads(buffer_record.payload_json or '[]')
            except (TypeError, ValueError):
                payload = []
            buffer_record.unlink()
        except Exception as error:
            _logger.warning(
                'WGS POS: could not recover subscription buffer for uuid=%s (%s)',
                order_uuid,
                error,
            )
            return []

        if not isinstance(payload, list):
            return []
        _logger.info('WGS POS: recovered %s buffered subscription configs for uuid=%s', len(payload), order_uuid)
        return payload

    def _wgs_apply_ui_subscription_line_config(self, ui_order):
        self.ensure_one()
        ui_configs = self._wgs_extract_ui_subscription_line_configs(ui_order)
        if not ui_configs:
            return
        self._wgs_apply_subscription_line_configs(ui_configs)

    def _wgs_apply_subscription_line_configs(self, ui_configs):
        self.ensure_one()
        if not ui_configs:
            return

        candidate_lines = self.lines.filtered(
            lambda line: line.qty > 0 and line.product_id and line.product_id.product_tmpl_id.recurring_invoice
        ).sorted(key=lambda line: line.id)
        if not candidate_lines:
            return

        unmatched_lines = candidate_lines
        for config in ui_configs:
            target_line = self._wgs_match_pos_line_for_ui_config(unmatched_lines, config)
            if not target_line:
                continue
            write_values = {}

            participant_ids = config.get('participant_ids') or []
            if isinstance(participant_ids, list):
                cleaned = []
                for value in participant_ids:
                    try:
                        participant_id = int(value)
                    except (TypeError, ValueError):
                        continue
                    if participant_id > 0:
                        cleaned.append(participant_id)
                if cleaned:
                    write_values['wgs_participant_ids_json'] = json.dumps(list(dict.fromkeys(cleaned)))

            pricing_snapshot = config.get('pricing_snapshot')
            if isinstance(pricing_snapshot, dict):
                write_values['wgs_pricing_snapshot_json'] = json.dumps(pricing_snapshot)

            for field_name, key_name in (
                ('wgs_subscription_plan_id', 'plan_id'),
                ('wgs_subscription_pricing_id', 'pricing_id'),
            ):
                try:
                    numeric = int(config.get(key_name) or 0)
                except (TypeError, ValueError):
                    numeric = 0
                if numeric > 0:
                    write_values[field_name] = numeric

            raw_end_date = config.get('end_date')
            if raw_end_date:
                end_date = fields.Date.to_date(raw_end_date)
                if end_date:
                    write_values['wgs_subscription_end_date'] = end_date
            raw_start_date = config.get('start_date')
            if raw_start_date:
                start_date = fields.Date.to_date(raw_start_date)
                if start_date:
                    write_values['wgs_subscription_start_date'] = start_date

            flow_value = str(config.get('flow') or 'new').strip().lower()
            write_values['wgs_subscription_flow'] = flow_value if flow_value in ('renewal', 'reenroll', 'upsale', 'pending_charge', 'cancellation_refund') else 'new'

            source_subscription_id = self._wgs_to_int(config.get('source_subscription_id'))
            if source_subscription_id > 0:
                write_values['wgs_subscription_source_id'] = source_subscription_id
            pending_move_id = self._wgs_to_int(config.get('pending_move_id'))
            if pending_move_id > 0:
                write_values['wgs_subscription_pending_move_id'] = pending_move_id
            refund_origin_line_id = self._wgs_to_int(config.get('refund_origin_line_id'))
            if refund_origin_line_id > 0:
                write_values['wgs_subscription_refund_origin_line_id'] = refund_origin_line_id

            discount_percent = self._wgs_to_float(config.get('discount_percent'))
            if discount_percent > 0:
                write_values['wgs_discount_percent'] = discount_percent
            discount_fixed_amount = self._wgs_to_float(config.get('discount_fixed_amount'))
            if discount_fixed_amount > 0:
                write_values['wgs_discount_fixed_amount'] = discount_fixed_amount
            discount_code = str(config.get('discount_code') or '').strip()
            if discount_code:
                write_values['wgs_discount_code'] = discount_code
            discount_label = str(config.get('discount_label') or '').strip()
            if discount_label:
                write_values['wgs_discount_label'] = discount_label
            authorized_employee_id = self._wgs_to_int(config.get('discount_authorized_employee_id'))
            if authorized_employee_id > 0:
                write_values['wgs_discount_authorized_employee_id'] = authorized_employee_id
            authorized_by = str(config.get('discount_authorized_by') or '').strip()
            if authorized_by:
                write_values['wgs_discount_authorized_by'] = authorized_by
            authorized_at = fields.Datetime.to_datetime(config.get('discount_authorized_at'))
            if authorized_at:
                write_values['wgs_discount_authorized_at'] = fields.Datetime.to_string(authorized_at)
            birthday_year = self._wgs_to_int(config.get('discount_birthday_year'))
            if birthday_year > 0:
                write_values['wgs_discount_birthday_year'] = birthday_year

            locked_values = self._wgs_get_locked_subscription_line_price_values_for_pos(
                config,
                fallback_price=target_line.price_unit,
            )
            if locked_values.get('price_unit') is not False:
                write_values['price_unit'] = locked_values['price_unit']
            write_values['discount'] = locked_values['discount']

            if write_values:
                target_line.write(write_values)
                _logger.info(
                    'WGS POS: applied UI config to pos.order.line %s -> %s',
                    target_line.id,
                    write_values,
                )
            unmatched_lines -= target_line

    def _wgs_align_partner_from_subscription_lines(self):
        self.ensure_one()

        partner_ids = set()
        for line in self.lines.filtered(lambda item: item.qty > 0 and item.wgs_has_subscription_configuration()):
            participant_ids = line.wgs_get_participant_ids()
            if participant_ids:
                partner_ids.add(int(participant_ids[0]))
                continue
            source_order = line.wgs_subscription_source_id
            if source_order and source_order.partner_id:
                partner_ids.add(source_order.partner_id.id)

        if not partner_ids:
            return
        if len(partner_ids) > 1:
            raise UserError(
                _('La orden POS contiene configuraciones de suscripción para más de un cliente. Usa un solo titular por ticket.')
            )

        partner = self.env['res.partner'].browse(next(iter(partner_ids))).exists()
        if partner and self.partner_id != partner:
            self.partner_id = partner.id

    @api.model
    def _wgs_extract_ui_subscription_line_configs(self, ui_order):
        output = []
        if not isinstance(ui_order, dict):
            return output

        raw_root_configs = ui_order.get('wgs_subscription_configs')
        if isinstance(raw_root_configs, str):
            try:
                raw_root_configs = json.loads(raw_root_configs)
            except (TypeError, ValueError):
                raw_root_configs = []
        if isinstance(raw_root_configs, list):
            for item in raw_root_configs:
                if not isinstance(item, dict):
                    continue
                config = self._wgs_extract_subscription_config_payload(item)
                config['product_id'] = self._wgs_to_int(item.get('product_id') or item.get('productId'))
                config['quantity'] = self._wgs_to_float(item.get('quantity') or item.get('qty'))
                output.append(config)
            if output:
                _logger.info('WGS POS: extracted %s root subscription configs from UI order.', len(output))
                return output

        raw_lines = ui_order.get('lines')
        if not isinstance(raw_lines, list):
            return output

        for raw_line in raw_lines:
            payload = self._wgs_find_best_payload_dict(raw_line)
            if not isinstance(payload, dict):
                continue
            config = self._wgs_extract_subscription_config_payload(payload)
            has_renewal_metadata = (
                str(config.get('flow') or '').strip().lower() in ('renewal', 'reenroll', 'pending_charge')
                or self._wgs_to_int(config.get('source_subscription_id')) > 0
                or self._wgs_to_int(config.get('pending_move_id')) > 0
            )
            if not (
                config.get('participant_ids')
                or config.get('plan_id')
                or config.get('pricing_id')
                or config.get('start_date')
                or config.get('end_date')
                or has_renewal_metadata
            ):
                continue

            config['product_id'] = self._wgs_to_int(payload.get('product_id') or payload.get('productId'))
            config['quantity'] = self._wgs_to_float(payload.get('qty') or payload.get('quantity') or payload.get('qty_ordered'))
            output.append(config)
        return output

    @api.model
    def _wgs_to_int(self, value):
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @api.model
    def _wgs_to_float(self, value):
        try:
            return abs(float(value or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @api.model
    def _wgs_to_signed_float(self, value):
        if value is False or value is None or value == '':
            return False
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return False

    @api.model
    def _wgs_find_best_payload_dict(self, raw_line):
        best = {}

        def _walk(node, depth=0):
            nonlocal best
            if depth > 6:
                return
            if isinstance(node, dict):
                score = 0
                if any(key in node for key in ('product_id', 'productId')):
                    score += 3
                if any(key in node for key in ('qty', 'quantity', 'qty_ordered')):
                    score += 2
                if any(key in node for key in ('wgs_subscription_config', 'wgs_participant_ids', 'wgsParticipantIds')):
                    score += 4
                if score > best.get('__score__', -1):
                    best = dict(node)
                    best['__score__'] = score
                for value in node.values():
                    _walk(value, depth + 1)
            elif isinstance(node, (list, tuple)):
                for value in node:
                    _walk(value, depth + 1)

        _walk(raw_line)
        best.pop('__score__', None)
        return best

    @api.model
    def _wgs_match_pos_line_for_ui_config(self, lines, config):
        if not lines:
            return self.env['pos.order.line']

        product_id = int(config.get('product_id') or 0)
        quantity = float(config.get('quantity') or 0.0)
        candidates = lines
        if product_id > 0:
            filtered = lines.filtered(lambda line: line.product_id.id == product_id)
            if filtered:
                candidates = filtered
        if quantity > 0:
            filtered = candidates.filtered(lambda line: abs(abs(line.qty) - quantity) < 0.0001)
            if filtered:
                candidates = filtered
        return candidates[:1]

    def _wgs_sync_subscription_sales(self):
        for pos_order in self:
            if not pos_order.partner_id:
                subscription_lines = pos_order.lines.filtered(
                    lambda line: (
                        line.qty > 0
                        and line.product_id
                        and line.product_id.product_tmpl_id.recurring_invoice
                        and line.wgs_has_subscription_configuration()
                    )
                )
                if subscription_lines:
                    raise UserError(
                        _('Debes seleccionar un cliente para vender productos de suscripción desde Punto de Venta.')
                    )

            # 1) Create subscription sales for normal/positive subscription lines.
            for line in pos_order.lines.filtered(
                lambda item: (
                    item.qty > 0
                    and item.product_id
                    and item.product_id.product_tmpl_id.recurring_invoice
                    and item.wgs_has_subscription_configuration()
                )
            ):
                if line.wgs_subscription_flow == 'renewal':
                    if line.wgs_subscription_source_id and line.wgs_sale_order_id == line.wgs_subscription_source_id:
                        continue
                    pos_order._wgs_process_subscription_renewal_line(line)
                    continue
                if line.wgs_subscription_flow == 'reenroll':
                    if (
                        line.wgs_subscription_source_id
                        and line.wgs_sale_order_id == line.wgs_subscription_source_id
                        and not pos_order._wgs_is_subscription_order_closed_for_reenroll(line.wgs_subscription_source_id)
                    ):
                        continue
                    pos_order._wgs_process_subscription_reenroll_line(line)
                    continue
                if line.wgs_subscription_flow == 'pending_charge':
                    pos_order._wgs_process_subscription_pending_charge_line(line)
                    continue
                if line.wgs_sale_order_id:
                    continue
                sale_order = pos_order._wgs_create_subscription_sale_order_from_line(line)
                line.wgs_sale_order_id = sale_order.id

            # 2) Cancel subscription sale orders when POS line is a refund.
            for line in pos_order.lines.filtered(
                lambda item: item.qty < 0 and item.product_id and item.product_id.product_tmpl_id.recurring_invoice
            ):
                pos_order._wgs_cancel_subscription_from_refund_line(line)

    @api.model
    def wgs_audit_paid_subscription_pos_sync_issues(self, date_from=False, date_to=False, limit=5000):
        lines = self._wgs_find_paid_subscription_pos_lines_for_audit(
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        issues = []
        for line in lines:
            issue = self._wgs_classify_paid_subscription_pos_line_sync_issue(line)
            if issue:
                issues.append(issue)
        return issues

    @api.model
    def wgs_repair_paid_subscription_pos_sync_issues(self, date_from=False, date_to=False, limit=5000, dry_run=True):
        issues = self.wgs_audit_paid_subscription_pos_sync_issues(
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        if dry_run:
            return issues

        repaired = []
        skipped = []
        lines_by_id = {
            line.id: line
            for line in self._wgs_find_paid_subscription_pos_lines_for_audit(
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )
        }
        for issue in issues:
            line = lines_by_id.get(issue.get('line_id'))
            if not line:
                skipped.append(dict(issue, repair_status='missing_line'))
                continue
            issue_type = issue.get('issue')
            try:
                if issue_type in ('explicit_flow_not_applied', 'configured_line_missing_sale_order'):
                    sale_order = self._wgs_repair_paid_subscription_pos_line_sync_issue(line)
                    repaired.append(
                        dict(
                            issue,
                            repair_status='repaired_by_line_sync',
                            repaired_sale_order_id=sale_order.id or False,
                            repaired_sale_order_name=sale_order.name or False,
                        )
                    )
                    continue
            except Exception as error:
                skipped.append(dict(issue, repair_status='error', error=str(error)))
                continue
            skipped.append(dict(issue, repair_status='not_safe'))

        return {
            'repaired': repaired,
            'skipped': skipped,
        }

    @api.model
    def wgs_repair_paid_subscription_pos_line_ids(self, line_ids, options_by_line=False, dry_run=True):
        """Repair explicit POS subscription lines by id.

        This is intentionally narrower than the broad audit repair. It only
        touches caller-selected lines and requires a paid POS order, a positive
        recurring product line and a POS customer.
        """
        options_by_line = options_by_line or {}
        if not isinstance(options_by_line, dict):
            options_by_line = {}
        repaired = []
        skipped = []
        lines = self.env['pos.order.line'].sudo().browse([int(line_id) for line_id in (line_ids or [])]).exists()
        for line in lines:
            options = options_by_line.get(str(line.id)) or options_by_line.get(line.id) or {}
            if not isinstance(options, dict):
                options = {}
            validation_error = self._wgs_validate_pos_line_for_targeted_subscription_repair(line)
            if validation_error:
                skipped.append(self._wgs_build_targeted_subscription_repair_result(line, 'skipped', validation_error))
                continue
            try:
                with self.env.cr.savepoint():
                    if dry_run:
                        repaired.append(
                            self._wgs_build_targeted_subscription_repair_result(
                                line,
                                'dry_run',
                                self._wgs_resolve_targeted_subscription_repair_action(line, options),
                            )
                        )
                        continue
                    sale_order = self._wgs_repair_single_paid_subscription_pos_line(line, options)
                    repaired.append(
                        self._wgs_build_targeted_subscription_repair_result(
                            line,
                            'repaired',
                            'Línea reparada y ligada a suscripción.',
                            sale_order=sale_order,
                        )
                    )
            except Exception as error:
                skipped.append(self._wgs_build_targeted_subscription_repair_result(line, 'error', str(error)))
        return {
            'dry_run': bool(dry_run),
            'repaired': repaired,
            'skipped': skipped,
        }

    def _wgs_validate_pos_line_for_targeted_subscription_repair(self, line):
        line.ensure_one()
        order = line.order_id
        if order.state not in ('paid', 'done', 'invoiced'):
            return _('La orden POS no está pagada/finalizada.')
        if not order.partner_id:
            return _('La orden POS no tiene cliente.')
        if line.qty <= 0:
            return _('La línea POS no es una venta positiva.')
        if not line.product_id or not line.product_id.product_tmpl_id.recurring_invoice:
            return _('La línea POS no corresponde a un producto recurrente.')
        return False

    def _wgs_resolve_targeted_subscription_repair_action(self, line, options):
        flow = self._wgs_resolve_targeted_subscription_repair_flow(line, options)
        if flow == 'new' and line.wgs_sale_order_id:
            return _('La línea ya está ligada a %(subscription)s.') % {'subscription': line.wgs_sale_order_id.name}
        if flow in ('renewal', 'reenroll', 'pending_charge') and not self._wgs_resolve_targeted_subscription_repair_source(line, options):
            return _('Falta source_subscription_id para reparar flujo %(flow)s.') % {'flow': flow}
        return _('Repararía la línea como flujo %(flow)s.') % {'flow': flow}

    def _wgs_build_targeted_subscription_repair_result(self, line, status, message, sale_order=False):
        linked_order = sale_order or line.wgs_sale_order_id
        return {
            'status': status,
            'message': str(message or ''),
            'line_id': line.id,
            'pos_order_id': line.order_id.id,
            'pos_order_name': line.order_id.name,
            'pos_reference': line.order_id.pos_reference or False,
            'partner_id': line.order_id.partner_id.id or False,
            'partner_name': line.order_id.partner_id.display_name or False,
            'product_id': line.product_id.id or False,
            'product': line.product_id.display_name or False,
            'flow': line.wgs_subscription_flow or False,
            'linked_order_id': linked_order.id or False,
            'linked_order_name': linked_order.name or False,
        }

    def _wgs_repair_single_paid_subscription_pos_line(self, line, options):
        line.ensure_one()
        order = line.order_id
        flow = self._wgs_resolve_targeted_subscription_repair_flow(line, options)
        values = {}

        source_order = self._wgs_resolve_targeted_subscription_repair_source(line, options)
        if source_order:
            values['wgs_subscription_source_id'] = source_order.id
        if flow:
            values['wgs_subscription_flow'] = flow

        start_date = self._wgs_resolve_targeted_subscription_repair_date(line, options, 'start_date')
        end_date = self._wgs_resolve_targeted_subscription_repair_date(line, options, 'end_date')
        if start_date:
            values['wgs_subscription_start_date'] = start_date
        if end_date:
            values['wgs_subscription_end_date'] = end_date
        if values:
            line.write(values)

        if flow == 'renewal':
            return order._wgs_process_subscription_renewal_line(line)
        if flow == 'reenroll':
            return order.with_context(wgs_allow_reenroll_repair_active_source=True)._wgs_process_subscription_reenroll_line(line)
        if flow == 'pending_charge':
            return order._wgs_process_subscription_pending_charge_line(line)
        if flow == 'upsale':
            raise UserError(_('La reparación dirigida de cambio de plan requiere revisión manual.'))
        if line.wgs_sale_order_id:
            return line.wgs_sale_order_id
        sale_order = order._wgs_create_subscription_sale_order_from_line(line)
        line.wgs_sale_order_id = sale_order.id
        return sale_order

    def _wgs_resolve_targeted_subscription_repair_flow(self, line, options):
        flow = str(options.get('flow') or line.wgs_subscription_flow or 'new').strip().lower()
        if flow not in ('new', 'renewal', 'reenroll', 'pending_charge', 'upsale'):
            flow = 'new'
        return flow

    def _wgs_resolve_targeted_subscription_repair_source(self, line, options):
        source_id = self._wgs_to_int(options.get('source_subscription_id') or options.get('source_order_id'))
        if source_id > 0:
            return self.env['sale.order'].sudo().browse(source_id).exists()
        return line.wgs_subscription_source_id.exists()

    def _wgs_resolve_targeted_subscription_repair_date(self, line, options, key):
        raw_value = options.get(key)
        if raw_value:
            return fields.Date.to_date(raw_value)
        if key == 'start_date':
            return line.wgs_get_subscription_start_date() or fields.Date.to_date(line.order_id.date_order)
        if key == 'end_date':
            return line.wgs_get_subscription_end_date()
        return False

    @api.model
    def _wgs_find_paid_subscription_pos_lines_for_audit(self, date_from=False, date_to=False, limit=5000):
        domain = [
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
            ('product_id.product_tmpl_id.recurring_invoice', '=', True),
            ('qty', '>', 0),
        ]
        if date_from:
            domain.append(('order_id.date_order', '>=', date_from))
        if date_to:
            domain.append(('order_id.date_order', '<=', date_to))
        return self.env['pos.order.line'].sudo().search(domain, order='id asc', limit=int(limit or 5000))

    def _wgs_repair_paid_subscription_pos_line_sync_issue(self, line):
        line.ensure_one()
        pos_order = line.order_id
        pos_order.ensure_one()

        flow = (line.wgs_subscription_flow or 'new').strip().lower()
        if flow == 'renewal':
            return pos_order._wgs_process_subscription_renewal_line(line)
        if flow == 'reenroll':
            return pos_order._wgs_process_subscription_reenroll_line(line)
        if flow == 'pending_charge':
            return pos_order._wgs_process_subscription_pending_charge_line(line)
        if line.wgs_sale_order_id:
            return line.wgs_sale_order_id

        sale_order = pos_order._wgs_create_subscription_sale_order_from_line(line)
        line.wgs_sale_order_id = sale_order.id
        return sale_order

    def _wgs_classify_paid_subscription_pos_line_sync_issue(self, line):
        line.ensure_one()

        flow = (line.wgs_subscription_flow or '').strip().lower()
        source_order = line.wgs_subscription_source_id.exists()
        linked_order = line.wgs_sale_order_id.exists()
        base_issue = self._wgs_build_paid_subscription_pos_line_issue(line)

        if flow in ('renewal', 'reenroll', 'pending_charge') and source_order:
            source_closed = self._wgs_is_subscription_order_closed_for_reenroll(source_order)
            if not linked_order or linked_order != source_order or source_closed:
                return dict(
                    base_issue,
                    issue='explicit_flow_not_applied',
                    safe_to_repair=True,
                    reason='La línea tiene flujo explícito y suscripción origen, pero no quedó aplicada sobre esa suscripción.',
                )

        if flow == 'new' and line.wgs_has_subscription_configuration() and not linked_order:
            reenroll_source = self._wgs_get_reenroll_source_for_new_same_product_flow(
                line.order_id.partner_id,
                line.product_id,
                company=line.order_id.company_id,
            )
            if reenroll_source:
                return dict(
                    base_issue,
                    issue='new_same_product_requires_reenroll',
                    safe_to_repair=False,
                    source_order_id=reenroll_source.id,
                    source_order_name=reenroll_source.name,
                    source_state=reenroll_source.subscription_state
                    if 'subscription_state' in reenroll_source._fields
                    else False,
                    reason='La línea se vendió como nueva, pero existe una suscripción cerrada/cancelada del mismo paquete; debe revisarse como reinscripción.',
                )

        if line.wgs_has_subscription_configuration() and not linked_order:
            return dict(
                base_issue,
                issue='configured_line_missing_sale_order',
                safe_to_repair=True,
                reason='La línea tiene metadata WGS pero no quedó ligada a una suscripción.',
            )

        if linked_order and self._wgs_is_subscription_order_closed_for_reenroll(linked_order):
            later_line = self._wgs_find_later_paid_subscription_line_for_same_subscription_customer(line)
            if later_line:
                return dict(
                    base_issue,
                    issue='linked_closed_has_later_payment',
                    safe_to_repair=False,
                    reason='La línea está ligada a una suscripción cerrada, pero existe un pago posterior del mismo cliente.',
                    later_pos_order_id=later_line.order_id.id,
                    later_pos_order_name=later_line.order_id.name,
                    later_pos_reference=later_line.order_id.pos_reference or False,
                    later_line_id=later_line.id,
                    later_linked_order=later_line.wgs_sale_order_id.name or False,
                )
            return dict(
                base_issue,
                issue='linked_closed_requires_manual_review',
                safe_to_repair=False,
                reason='La línea está ligada a una suscripción cerrada sin flujo explícito. Puede ser reinscripción o venta nueva diferente; requiere decisión manual.',
            )

        return False

    def _wgs_build_paid_subscription_pos_line_issue(self, line):
        linked_order = line.wgs_sale_order_id
        source_order = line.wgs_subscription_source_id
        return {
            'pos_order_id': line.order_id.id,
            'pos_order_name': line.order_id.name,
            'pos_reference': line.order_id.pos_reference or False,
            'pos_date_order': fields.Datetime.to_string(line.order_id.date_order) if line.order_id.date_order else False,
            'line_id': line.id,
            'product': line.product_id.display_name,
            'partner_id': line.order_id.partner_id.id or False,
            'partner_name': line.order_id.partner_id.display_name or False,
            'flow': line.wgs_subscription_flow or False,
            'source_order_id': source_order.id or False,
            'source_order_name': source_order.name or False,
            'source_state': source_order.subscription_state if source_order and 'subscription_state' in source_order._fields else False,
            'linked_order_id': linked_order.id or False,
            'linked_order_name': linked_order.name or False,
            'linked_state': linked_order.subscription_state if linked_order and 'subscription_state' in linked_order._fields else False,
            'line_start_date': fields.Date.to_string(line.wgs_subscription_start_date) if line.wgs_subscription_start_date else False,
            'line_end_date': fields.Date.to_string(line.wgs_subscription_end_date) if line.wgs_subscription_end_date else False,
        }

    def _wgs_find_later_paid_subscription_line_for_same_subscription_customer(self, line):
        line.ensure_one()
        partner = (line.wgs_sale_order_id.partner_id or line.wgs_subscription_source_id.partner_id or line.order_id.partner_id).exists()
        if not partner:
            return self.env['pos.order.line']
        line_date = line.order_id.date_order or False
        domain = [
            ('id', '!=', line.id),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
            ('order_id.partner_id', '=', partner.id),
            ('product_id.product_tmpl_id.recurring_invoice', '=', True),
            ('qty', '>', 0),
        ]
        if line_date:
            domain.append(('order_id.date_order', '>', line_date))
        return self.env['pos.order.line'].sudo().search(domain, order='id desc', limit=1)

    def _wgs_process_subscription_renewal_line(self, line):
        self.ensure_one()

        source_order = line.wgs_subscription_source_id or line.wgs_sale_order_id
        if not source_order and self.partner_id:
            source_order = self._wgs_find_active_subscription_for_partner(self.partner_id, company=self.company_id)[:1]
        source_order = source_order.exists() if source_order else self.env['sale.order']
        if not source_order:
            raise UserError(_('No se encontró la suscripción origen para cobrar la renovación en POS.'))
        if not self._wgs_order_has_subscription_signal(source_order):
            raise UserError(_('La orden origen no corresponde a una suscripción válida para renovación.'))
        if not self._wgs_is_subscription_order_active_for_upsell(source_order):
            raise UserError(_('La suscripción origen no está activa para renovación.'))

        recurring_lines = source_order.order_line.filtered(lambda so_line: self._wgs_is_recurring_so_line(so_line))
        if not recurring_lines:
            raise UserError(_('La suscripción origen no tiene líneas recurrentes configuradas.'))

        source_line = recurring_lines.filtered(lambda so_line: so_line.product_id.id == line.product_id.id)[:1]
        if not source_line:
            source_line = recurring_lines.sorted(key=lambda so_line: so_line.id)[:1]

        today = fields.Date.context_today(self)
        _period_start, period_end = self._wgs_get_current_subscription_period_bounds(source_order, today=today)
        recurrence_delta = self._wgs_get_order_recurrence_delta(source_order)
        if period_end and today < period_end:
            renewal_anchor = period_end
        else:
            renewal_anchor = today
        next_billing_date = renewal_anchor + recurrence_delta

        values = {}
        next_field = self._wgs_find_subscription_next_invoice_date_field(source_order)
        if next_field:
            values[next_field] = next_billing_date
        end_field = self._wgs_find_subscription_end_date_field(source_order)
        if end_field:
            values[end_field] = self._wgs_to_date(next_billing_date) - timedelta(days=1)
        if values:
            source_order.write(values)

        self._wgs_link_pos_and_sale_records(
            pos_line=line,
            sale_order=source_order,
            sale_order_line=source_line,
        )
        line.write({
            'wgs_sale_order_id': source_order.id,
            'wgs_subscription_flow': 'renewal',
            'wgs_subscription_source_id': source_order.id,
        })

        amount_paid = abs(float(line.qty or 0.0)) * float(line.price_unit or 0.0)
        if hasattr(source_order, 'message_post'):
            source_order.message_post(
                body=_(
                    'Pago recurrente recibido en POS %(pos)s por %(amount).2f. Próximo cobro: %(next_date)s.'
                ) % {
                    'pos': self.pos_reference or self.name,
                    'amount': amount_paid,
                    'next_date': fields.Date.to_string(next_billing_date),
                }
            )

        _logger.info(
            'WGS POS: renewal payment synced for subscription %s from POS %s line %s (next=%s, amount=%s)',
            source_order.name,
            self.pos_reference or self.name,
            line.id,
            next_billing_date,
            amount_paid,
        )
        return source_order

    def _wgs_process_subscription_reenroll_line(self, line):
        self.ensure_one()

        source_order = line.wgs_subscription_source_id or line.wgs_sale_order_id
        source_order = source_order.exists() if source_order else self.env['sale.order']
        if not source_order:
            raise UserError(_('No se encontró la suscripción origen para aplicar la reinscripción en POS.'))
        if not self._wgs_order_has_subscription_signal(source_order):
            raise UserError(_('La orden origen no corresponde a una suscripción válida para reinscripción.'))
        allow_active_repair = bool(
            self.env.context.get('wgs_allow_reenroll_repair_active_source')
            and line.wgs_sale_order_id
            and line.wgs_sale_order_id == source_order
        )
        if not self._wgs_is_subscription_order_closed_for_reenroll(source_order) and not allow_active_repair:
            raise UserError(_('La suscripción origen no está cerrada/cancelada para reinscripción.'))

        product = line.product_id
        qty = abs(line.qty or 0.0) or 1.0
        max_total = int((product.max_participants_total or 1) * qty)
        if max_total < 1:
            max_total = 1

        participant_ids = line.wgs_get_participant_ids()
        holder_partner = source_order.partner_id or self.partner_id
        if holder_partner and holder_partner.id not in participant_ids:
            participant_ids.insert(0, holder_partner.id)
        participant_ids = list(dict.fromkeys(participant_ids))
        if len(participant_ids) > max_total:
            raise UserError(
                _(
                    'No puedes asignar %(current)s participantes para %(product)s. El máximo permitido es %(max)s.'
                )
                % {
                    'current': len(participant_ids),
                    'product': product.display_name,
                    'max': max_total,
                }
            )

        pricing_state = self._wgs_get_persisted_subscription_pricing_from_pos_line(line)
        recurring_price_unit = pricing_state['price_unit']
        recurring_plan_id = pricing_state['plan_id']
        recurring_pricing_id = pricing_state['pricing_id']
        plan_record = pricing_state['plan_record']
        today = fields.Date.context_today(self)
        subscription_start_date = (
            pricing_state.get('subscription_start_date')
            or line.wgs_get_subscription_start_date()
            or today
        )
        subscription_end_date = (
            pricing_state.get('subscription_end_date')
            or line.wgs_get_subscription_end_date()
        )
        next_billing_date = pricing_state.get('next_billing_date') or False
        if plan_record and not subscription_end_date:
            subscription_end_date = self._wgs_get_plan_period_end_date(plan_record, subscription_start_date)
        if plan_record and not next_billing_date:
            next_billing_date = self._wgs_get_plan_min_end_threshold(plan_record, subscription_start_date)
        if self._wgs_product_has_single_day_term(product):
            subscription_end_date = subscription_start_date
            next_billing_date = False

        source_line = source_order.order_line.filtered(lambda so_line: self._wgs_is_recurring_so_line(so_line))[:1]
        if not source_line:
            raise UserError(_('La suscripción origen no tiene líneas recurrentes para aplicar la reinscripción.'))
        line_values = self._wgs_build_reenroll_source_line_values(
            source_line=source_line,
            pos_line=line,
            product=product,
            qty=qty,
            recurring_price_unit=recurring_price_unit,
            recurring_plan_id=recurring_plan_id,
            recurring_pricing_id=recurring_pricing_id,
        )
        if line_values:
            source_line.write(line_values)

        self._wgs_sync_subscription_metadata(
            sale_order=source_order,
            participant_ids=participant_ids,
            contract_date=today,
            subscription_start_date=subscription_start_date,
            subscription_end_date=subscription_end_date,
            next_billing_date=next_billing_date,
            clear_next_billing_date=self._wgs_product_has_single_day_term(product),
        )
        self._wgs_reactivate_subscription_order_for_pos(source_order)
        if hasattr(source_order, '_wgs_sync_access_control_people'):
            source_order.with_context(access_sync_priority=True)._wgs_sync_access_control_people()

        self._wgs_link_pos_and_sale_records(
            pos_line=line,
            sale_order=source_order,
            sale_order_line=source_line,
        )
        line.write({
            'wgs_sale_order_id': source_order.id,
            'wgs_subscription_flow': 'reenroll',
            'wgs_subscription_source_id': source_order.id,
        })

        amount_paid = abs(float(line.qty or 0.0)) * float(line.price_unit or 0.0)
        if hasattr(source_order, 'message_post'):
            source_order.message_post(
                body=_(
                    'Reinscripción pagada en POS %(pos)s por %(amount).2f. Vigencia: %(start)s - %(end)s.'
                ) % {
                    'pos': self.pos_reference or self.name,
                    'amount': amount_paid,
                    'start': fields.Date.to_string(subscription_start_date),
                    'end': fields.Date.to_string(subscription_end_date) if subscription_end_date else '-',
                }
            )

        _logger.info(
            'WGS POS: reenroll payment synced for subscription %s from POS %s line %s (start=%s, end=%s, next=%s, amount=%s)',
            source_order.name,
            self.pos_reference or self.name,
            line.id,
            subscription_start_date,
            subscription_end_date,
            next_billing_date,
            amount_paid,
        )
        return source_order

    def _wgs_build_reenroll_source_line_values(
        self,
        *,
        source_line,
        pos_line,
        product,
        qty,
        recurring_price_unit,
        recurring_plan_id=False,
        recurring_pricing_id=False,
    ):
        line_fields = source_line._fields
        values = {}
        if 'product_id' in line_fields:
            values['product_id'] = product.id
        if 'name' in line_fields:
            values['name'] = pos_line.full_product_name or product.display_name
        qty_field_name = next(
            (
                field_name
                for field_name in ('product_uom_qty', 'quantity', 'qty')
                if field_name in line_fields
            ),
            False,
        )
        if qty_field_name:
            values[qty_field_name] = qty
        uom_field_name = next(
            (
                field_name
                for field_name in ('product_uom_id', 'product_uom', 'uom_id')
                if field_name in line_fields
            ),
            False,
        )
        if uom_field_name and product.uom_id:
            values[uom_field_name] = product.uom_id.id
        if 'price_unit' in line_fields:
            values['price_unit'] = recurring_price_unit
        if 'discount' in line_fields:
            values['discount'] = pos_line.discount
        if recurring_plan_id:
            self._wgs_assign_many2one_value(
                values=values,
                fields_map=line_fields,
                value_id=recurring_plan_id,
                preferred_field_names=('subscription_plan_id', 'plan_id', 'recurring_plan_id'),
                comodel_checker=self._wgs_is_plan_model_name,
            )
        if recurring_pricing_id:
            self._wgs_assign_many2one_value(
                values=values,
                fields_map=line_fields,
                value_id=recurring_pricing_id,
                preferred_field_names=('subscription_pricing_id', 'pricing_id', 'recurring_pricing_id'),
                comodel_checker=self._wgs_is_pricing_model_name,
            )
        return values

    def _wgs_reactivate_subscription_order_for_pos(self, source_order):
        source_order.ensure_one()
        progress_state = self._wgs_find_subscription_progress_state_value(source_order)
        if not progress_state:
            raise UserError(_('No se pudo resolver el estado activo/en progreso para reactivar la suscripción.'))
        source_order.write({'subscription_state': progress_state})
        return True

    def _wgs_find_subscription_progress_state_value(self, sale_order):
        sale_order.ensure_one()
        field = sale_order._fields.get('subscription_state')
        if not field:
            return False
        selection = field.selection
        if callable(selection):
            try:
                selection = selection(sale_order)
            except TypeError:
                selection = selection(self.env)
        selection = selection or []
        tokens = ('progress', 'in_progress', 'in progress', 'en progreso')
        fallback = False
        for value, label in selection:
            value_text = str(value or '').strip().lower()
            label_text = str(label or '').strip().lower()
            haystack = ' '.join(filter(None, [value_text, label_text]))
            if value_text == 'progress':
                fallback = value
            if any(token in haystack for token in tokens):
                return value
        return fallback

    def _wgs_process_subscription_pending_charge_line(self, line):
        self.ensure_one()

        source_order = line.wgs_subscription_source_id or line.wgs_sale_order_id
        if not source_order and self.partner_id:
            source_order = self._wgs_find_active_subscription_for_partner(self.partner_id, company=self.company_id)[:1]
        source_order = source_order.exists() if source_order else self.env['sale.order']
        if not source_order:
            raise UserError(_('No se encontró la suscripción origen para cobrar el pendiente en POS.'))
        if not self._wgs_order_has_subscription_signal(source_order):
            raise UserError(_('La orden origen no corresponde a una suscripción válida para cobro pendiente.'))

        pending_invoice = line.wgs_subscription_pending_move_id
        if pending_invoice:
            pending_invoice = pending_invoice.exists()
        if not pending_invoice:
            pending_invoice = self._wgs_get_pending_invoice_from_subscription(source_order)
        if not pending_invoice:
            raise UserError(_('La suscripción origen no tiene facturas pendientes por cobrar.'))

        self._wgs_reconcile_pending_invoice_from_pos_order(pending_invoice, amount=abs(float(line.price_unit or 0.0) * float(line.qty or 0.0)))
        self._wgs_link_pos_and_sale_records(pos_line=line, sale_order=source_order)
        line.write({
            'wgs_sale_order_id': source_order.id,
            'wgs_subscription_flow': 'pending_charge',
            'wgs_subscription_source_id': source_order.id,
            'wgs_subscription_pending_move_id': pending_invoice.id,
        })

        if hasattr(pending_invoice, 'message_post'):
            pending_invoice.message_post(
                body=_('Pago de factura pendiente recibido en POS %(pos)s por %(amount).2f.') % {
                    'pos': self.pos_reference or self.name,
                    'amount': abs(float(line.price_unit or 0.0) * float(line.qty or 0.0)),
                }
            )
        if hasattr(source_order, 'message_post'):
            source_order.message_post(
                body=_('Cobro pendiente aplicado en POS a la factura %(invoice)s.') % {
                    'invoice': pending_invoice.name or pending_invoice.display_name,
                }
            )
        _logger.info(
            'WGS POS: pending charge synced for subscription %s invoice %s from POS %s line %s',
            source_order.name,
            pending_invoice.name or pending_invoice.id,
            self.pos_reference or self.name,
            line.id,
        )
        return source_order

    def _wgs_get_pending_invoice_from_subscription(self, source_order, pending_move_id=False):
        self.ensure_one()
        invoice_model = self.env['account.move'].sudo()
        source_order = source_order.exists() if source_order else self.env['sale.order']
        if not source_order:
            return invoice_model

        pending_moves = source_order._wgs_get_pending_invoice_records_for_pos()
        try:
            pending_move_id = int(pending_move_id or 0)
        except (TypeError, ValueError):
            pending_move_id = 0
        if pending_move_id > 0:
            return pending_moves.filtered(lambda move: move.id == pending_move_id)[:1]
        return pending_moves[:1]

    def _wgs_reconcile_pending_invoice_from_pos_order(self, invoice, amount=False):
        self.ensure_one()
        invoice = invoice.sudo().exists()
        if not invoice:
            raise UserError(_('La factura pendiente ya no existe.'))

        target_amount = round(max(float(amount or 0.0), 0.0), 2)
        residual_amount = round(max(float(getattr(invoice, 'amount_residual', 0.0) or 0.0), 0.0), 2)
        if target_amount > 0.0 and residual_amount > 0.0 and target_amount - residual_amount > 0.01:
            raise UserError(_('El cobro POS supera el saldo pendiente de la factura seleccionada.'))

        invoice_lines = invoice.line_ids.filtered(
            lambda move_line: (
                getattr(move_line.account_id, 'account_type', False) == 'asset_receivable'
                and not move_line.reconciled
            )
        )
        if not invoice_lines:
            raise UserError(_('No se encontraron líneas contables por cobrar en la factura pendiente.'))

        pos_receivable_lines = self._wgs_get_pos_receivable_move_lines(invoice.partner_id)
        if not pos_receivable_lines:
            raise UserError(_('No se encontraron líneas contables del ticket POS para aplicar el cobro pendiente.'))

        target_account_ids = set(invoice_lines.mapped('account_id').ids)
        if target_account_ids:
            same_account_lines = pos_receivable_lines.filtered(lambda move_line: move_line.account_id.id in target_account_ids)
            if same_account_lines:
                pos_receivable_lines = same_account_lines

        (invoice_lines | pos_receivable_lines).reconcile()
        return True

    def _wgs_get_pos_receivable_move_lines(self, partner=False):
        self.ensure_one()
        account_move_model = self.env['account.move'].sudo()
        pos_payment_model = self.env['pos.payment'].sudo() if 'pos.payment' in self.env.registry else self.env['pos.order']

        related_moves = account_move_model.browse()
        for field_name, field in self._fields.items():
            if getattr(field, 'comodel_name', '') != 'account.move':
                continue
            value = self[field_name]
            if field.type == 'many2one':
                if value:
                    related_moves |= value.sudo()
            else:
                related_moves |= value.sudo()

        payment_records = pos_payment_model.browse()
        for field_name, field in self._fields.items():
            if getattr(field, 'comodel_name', '') != 'pos.payment':
                continue
            value = self[field_name]
            if field.type == 'many2one':
                if value:
                    payment_records |= value.sudo()
            else:
                payment_records |= value.sudo()

        for payment in payment_records:
            for field_name, field in payment._fields.items():
                if getattr(field, 'comodel_name', '') != 'account.move':
                    continue
                value = payment[field_name]
                if field.type == 'many2one':
                    if value:
                        related_moves |= value.sudo()
                else:
                    related_moves |= value.sudo()

        receivable_lines = related_moves.mapped('line_ids').filtered(
            lambda move_line: (
                getattr(move_line.account_id, 'account_type', False) == 'asset_receivable'
                and not move_line.reconciled
            )
        )
        if partner:
            receivable_lines = receivable_lines.filtered(lambda move_line: move_line.partner_id == partner)
        return receivable_lines.sorted(key=lambda move_line: (move_line.date or fields.Date.today(), move_line.id))

    def _wgs_resolve_upsell_source_order_for_line(self, line):
        self.ensure_one()
        source_order = line.wgs_subscription_source_id
        if not source_order and self.partner_id:
            source_order = self._wgs_find_active_subscription_for_partner(self.partner_id, company=self.company_id)[:1]
        source_order = source_order.exists() if source_order else self.env['sale.order']
        if not source_order:
            raise UserError(_('No se encontró la suscripción origen para ejecutar el upsale en POS.'))
        if not self._wgs_order_has_subscription_signal(source_order):
            raise UserError(_('La orden origen no corresponde a una suscripción válida para upsale.'))
        if not self._wgs_is_subscription_order_active_for_upsell(source_order):
            raise UserError(_('La suscripción origen no está activa para upsale.'))
        return source_order

    def _wgs_get_persisted_subscription_pricing_from_pos_line(self, line):
        self.ensure_one()
        line.ensure_one()

        product = line.product_id
        snapshot = {}
        raw_snapshot = line.wgs_pricing_snapshot_json or False
        if raw_snapshot:
            try:
                snapshot = json.loads(raw_snapshot)
            except (TypeError, ValueError):
                snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}

        recurring_price_unit = round(
            max(
                abs(
                    float(
                        snapshot.get('recurring_price')
                        or line.price_unit
                        or 0.0
                    )
                ),
                0.0,
            ),
            2,
        )
        recurring_plan_id = self._wgs_to_int(line.wgs_subscription_plan_id or snapshot.get('plan_id')) or False
        recurring_pricing_id = self._wgs_to_int(line.wgs_subscription_pricing_id or snapshot.get('pricing_id')) or False
        source_order = self.env['sale.order']
        source_subscription_id = self._wgs_to_int(snapshot.get('source_subscription_id'))
        if line.wgs_subscription_source_id:
            source_order = line.wgs_subscription_source_id
        elif source_subscription_id > 0:
            source_order = self.env['sale.order'].browse(source_subscription_id).exists()
        credit_amount = round(max(float(snapshot.get('credit_amount') or 0.0), 0.0), 2)
        persisted_subscription_start_date = fields.Date.to_date(
            snapshot.get('subscription_start_date')
            or line.wgs_subscription_start_date
            or False
        )
        persisted_subscription_end_date = fields.Date.to_date(
            snapshot.get('subscription_end_date')
            or line.wgs_subscription_end_date
            or False
        )
        persisted_next_billing_date = fields.Date.to_date(snapshot.get('next_billing_date') or False)

        if line.wgs_subscription_flow == 'upsale':
            if not source_order:
                source_order = self._wgs_resolve_upsell_source_order_for_line(line)
            if not credit_amount:
                credit_amount = round(max(float(self._wgs_get_upsale_source_recurring_amount(source_order) or 0.0), 0.0), 2)
            if not snapshot.get('recurring_price'):
                recurring_price_unit = round(max(recurring_price_unit + credit_amount, 0.0), 2)
            if not (persisted_subscription_start_date and persisted_subscription_end_date):
                upsale_schedule = self._wgs_get_upsale_schedule_from_source(source_order)
                persisted_subscription_start_date = (
                    persisted_subscription_start_date
                    or upsale_schedule.get('subscription_start_date')
                    or False
                )
                persisted_subscription_end_date = (
                    persisted_subscription_end_date
                    or upsale_schedule.get('subscription_end_date')
                    or False
                )
                persisted_next_billing_date = (
                    persisted_next_billing_date
                    or upsale_schedule.get('next_billing_date')
                    or False
                )

        if recurring_pricing_id and not recurring_plan_id and 'sale.subscription.pricing' in self.env.registry:
            pricing_record = self.env['sale.subscription.pricing'].browse(int(recurring_pricing_id)).exists()
            if pricing_record:
                recurring_plan_id = self._wgs_extract_plan_id_from_pricing(pricing_record)
        if not recurring_plan_id:
            recurring_plan_id = self._wgs_extract_plan_id_from_product(product)
        if (
            not recurring_plan_id
            and line.wgs_subscription_flow in ('renewal', 'reenroll')
            and source_order
        ):
            recurring_plan_id = self._wgs_extract_plan_id_from_subscription_source_line(
                source_order,
                product,
            )
        if not recurring_plan_id:
            _logger.warning(
                'WGS POS: No persisted recurring plan resolved for product %s (id=%s). flow=%s pricing_id=%s',
                product.display_name,
                product.id,
                line.wgs_subscription_flow,
                recurring_pricing_id,
            )

        plan_record = self._wgs_resolve_plan_record(
            product=product,
            plan_id=recurring_plan_id,
            pricing_id=recurring_pricing_id,
        )
        return {
            'price_unit': recurring_price_unit,
            'plan_id': recurring_plan_id,
            'pricing_id': recurring_pricing_id,
            'plan_record': plan_record,
            'source_order': source_order,
            'credit_amount': credit_amount,
            'subscription_start_date': persisted_subscription_start_date,
            'subscription_end_date': persisted_subscription_end_date,
            'next_billing_date': persisted_next_billing_date,
        }

    def _wgs_extract_plan_id_from_subscription_source_line(self, source_order, product):
        source_order = source_order.exists()
        product = product.exists()
        if not source_order or not product:
            return False
        recurring_lines = source_order.order_line.filtered(lambda so_line: self._wgs_is_recurring_so_line(so_line))
        matching_lines = recurring_lines.filtered(lambda so_line: so_line.product_id == product)
        source_line = (matching_lines or recurring_lines)[:1]
        if not source_line:
            return False
        for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
            if field_name in source_line._fields and source_line[field_name]:
                return source_line[field_name].id
        return False

    def _wgs_create_subscription_sale_order_from_line(self, line):
        self.ensure_one()

        product = line.product_id
        if line.wgs_subscription_flow == 'new':
            blocking_subscription = self._wgs_get_blocking_subscription_for_new_flow(
                self.partner_id,
                company=self.company_id,
            )
            if blocking_subscription:
                raise UserError(
                    self._wgs_get_blocking_subscription_for_new_flow_message(blocking_subscription)
                )
            reenroll_source = self._wgs_get_reenroll_source_for_new_same_product_flow(
                self.partner_id,
                product,
                company=self.company_id,
            )
            if reenroll_source:
                raise UserError(
                    self._wgs_get_reenroll_required_for_new_same_product_message(
                        reenroll_source,
                        product,
                    )
                )
        qty = abs(line.qty)
        max_total = int((product.max_participants_total or 1) * qty)
        if max_total < 1:
            max_total = 1

        participant_ids = line.wgs_get_participant_ids()
        if self.partner_id.id not in participant_ids:
            participant_ids.insert(0, self.partner_id.id)

        participant_ids = list(dict.fromkeys(participant_ids))
        if len(participant_ids) > max_total:
            raise UserError(
                _(
                    'No puedes asignar %(current)s participantes para %(product)s. El máximo permitido es %(max)s.'
                )
                % {
                    'current': len(participant_ids),
                    'product': product.display_name,
                    'max': max_total,
                }
            )

        pricing_state = self._wgs_get_persisted_subscription_pricing_from_pos_line(line)
        recurring_price_unit = pricing_state['price_unit']
        recurring_plan_id = pricing_state['plan_id']
        recurring_pricing_id = pricing_state['pricing_id']
        plan_record = pricing_state['plan_record']
        today = fields.Date.context_today(self)
        subscription_start_date = (
            pricing_state.get('subscription_start_date')
            or line.wgs_get_subscription_start_date()
            or today
        )
        subscription_end_date = (
            pricing_state.get('subscription_end_date')
            or line.wgs_get_subscription_end_date()
        )
        sale_start_date = subscription_start_date
        next_billing_date = pricing_state.get('next_billing_date') or False

        sale_order_line_fields = self.env['sale.order.line']._fields
        line_values = {'product_id': product.id}
        if 'name' in sale_order_line_fields:
            line_values['name'] = line.full_product_name or product.display_name

        qty_field_name = next(
            (
                field_name
                for field_name in ('product_uom_qty', 'quantity', 'qty')
                if field_name in sale_order_line_fields
            ),
            False,
        )
        if qty_field_name:
            line_values[qty_field_name] = qty

        uom_field_name = next(
            (
                field_name
                for field_name in ('product_uom_id', 'product_uom', 'uom_id')
                if field_name in sale_order_line_fields
            ),
            False,
        )
        if uom_field_name and product.uom_id:
            line_values[uom_field_name] = product.uom_id.id

        if 'price_unit' in sale_order_line_fields:
            line_values['price_unit'] = recurring_price_unit
        if 'discount' in sale_order_line_fields:
            line_values['discount'] = line.discount

        if recurring_plan_id:
            for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
                if field_name in sale_order_line_fields:
                    line_values[field_name] = recurring_plan_id
            self._wgs_assign_many2one_value(
                values=line_values,
                fields_map=sale_order_line_fields,
                value_id=recurring_plan_id,
                preferred_field_names=('subscription_plan_id', 'plan_id', 'recurring_plan_id'),
                comodel_checker=self._wgs_is_plan_model_name,
            )
        if recurring_pricing_id:
            for field_name in ('subscription_pricing_id', 'pricing_id', 'recurring_pricing_id'):
                if field_name in sale_order_line_fields:
                    line_values[field_name] = recurring_pricing_id
            self._wgs_assign_many2one_value(
                values=line_values,
                fields_map=sale_order_line_fields,
                value_id=recurring_pricing_id,
                preferred_field_names=('subscription_pricing_id', 'pricing_id', 'recurring_pricing_id'),
                comodel_checker=self._wgs_is_pricing_model_name,
            )

        contract_date = fields.Date.context_today(self)
        upsell_source_order = self.env['sale.order']
        if line.wgs_subscription_flow == 'upsale':
            upsell_source_order = pricing_state['source_order'] or self._wgs_resolve_upsell_source_order_for_line(line)
        if upsell_source_order:
            upsale_schedule = self._wgs_get_upsale_schedule_from_source(
                upsell_source_order,
                today=today,
            )
            if line.wgs_subscription_flow == 'upsale':
                sale_start_date = (
                    pricing_state.get('subscription_start_date')
                    or upsale_schedule['subscription_start_date']
                    or sale_start_date
                )
                subscription_start_date = sale_start_date
                subscription_end_date = (
                    pricing_state.get('subscription_end_date')
                    or upsale_schedule['subscription_end_date']
                    or subscription_end_date
                )
                next_billing_date = (
                    pricing_state.get('next_billing_date')
                    or upsale_schedule['next_billing_date']
                    or next_billing_date
                )
            else:
                sale_start_date = upsale_schedule['sale_start_date']
                subscription_start_date = sale_start_date
                subscription_end_date = upsale_schedule['subscription_end_date']
                next_billing_date = upsale_schedule['next_billing_date']
        elif plan_record:
            next_billing_date = self._wgs_get_plan_min_end_threshold(plan_record, sale_start_date)
            subscription_end_date = self._wgs_get_plan_period_end_date(plan_record, sale_start_date)
        if self._wgs_product_has_single_day_term(product):
            subscription_start_date = sale_start_date
            subscription_end_date = sale_start_date
            next_billing_date = False
        if upsell_source_order:
            recurring_total = max(0.0, float(recurring_price_unit or 0.0) * float(qty or 0.0))
            paid_total = max(0.0, float(line.price_unit or 0.0) * float(qty or 0.0))
            credit_from_pos = max(0.0, recurring_total - paid_total)
            upsell_line_values = dict(line_values)
            if credit_from_pos > 0 and 'name' in sale_order_line_fields:
                base_name = upsell_line_values.get('name') or product.display_name
                upsell_line_values['name'] = _('%(name)s (Complemento por upgrade POS)') % {
                    'name': base_name,
                }

            # Immediate upgrade flow for POS:
            # create a fresh subscription order (not renewal quote), apply credit as bonus line,
            # confirm immediately, then close previous subscription.
            sale_order_fields = self.env['sale.order']._fields
            upsell_order_values = {
                'partner_id': self.partner_id.id,
                'origin': _('%(origin)s | Upsale POS de %(source)s') % {
                    'origin': self.pos_reference or self.name,
                    'source': upsell_source_order.name,
                },
                'client_order_ref': _('%(origin)s | Upsale POS de %(source)s') % {
                    'origin': self.pos_reference or self.name,
                    'source': upsell_source_order.name,
                },
                'company_id': self.company_id.id,
                'order_line': [Command.create(upsell_line_values)],
            }
            if credit_from_pos > 0:
                bonus_line_values = self._wgs_build_upgrade_bonus_line_values(credit_amount=credit_from_pos)
                if bonus_line_values:
                    upsell_order_values['order_line'].append(Command.create(bonus_line_values))

            if 'date_order' in sale_order_fields:
                upsell_order_values['date_order'] = self._wgs_convert_date_for_field_value(
                    contract_date,
                    sale_order_fields.get('date_order'),
                )
            if 'pricelist_id' in self._fields and self.pricelist_id:
                upsell_order_values['pricelist_id'] = self.pricelist_id.id

            self._wgs_assign_date_field(
                values=upsell_order_values,
                fields_map=sale_order_fields,
                date_value=contract_date,
                preferred_field_names=('first_contract_date', 'contract_date', 'date_contract'),
            )
            self._wgs_assign_date_field(
                values=upsell_order_values,
                fields_map=sale_order_fields,
                date_value=sale_start_date,
                preferred_field_names=('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date'),
            )
            if subscription_end_date:
                self._wgs_assign_date_field(
                    values=upsell_order_values,
                    fields_map=sale_order_fields,
                    date_value=subscription_end_date,
                    preferred_field_names=('end_date', 'date_end', 'subscription_end_date', 'recurring_end_date'),
                )
            if recurring_plan_id:
                for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
                    if field_name in sale_order_fields and field_name not in upsell_order_values:
                        upsell_order_values[field_name] = recurring_plan_id
                self._wgs_assign_many2one_value(
                    values=upsell_order_values,
                    fields_map=sale_order_fields,
                    value_id=recurring_plan_id,
                    preferred_field_names=('subscription_plan_id', 'plan_id', 'recurring_plan_id'),
                    comodel_checker=self._wgs_is_plan_model_name,
                )

            upsell_order = self.env['sale.order'].create(upsell_order_values)
            if 'participant_ids' in upsell_order._fields:
                upsell_order.write({'participant_ids': [Command.set(participant_ids)]})

            sale_order_line = upsell_order.order_line.filtered(lambda so_line: so_line.product_id == product)[:1]
            if not sale_order_line:
                sale_order_line = upsell_order.order_line[:1]
            self._wgs_link_pos_and_sale_records(
                pos_line=line,
                sale_order=upsell_order,
                sale_order_line=sale_order_line,
            )

            if upsell_order.state in ('draft', 'sent'):
                upsell_order.action_confirm()

            # On upsell we preserve the original subscription schedule from the source
            # and only charge the delta between destination and source packages.
            self._wgs_sync_subscription_metadata(
                sale_order=upsell_order,
                participant_ids=participant_ids,
                contract_date=contract_date,
                subscription_start_date=sale_start_date,
                subscription_end_date=subscription_end_date,
                next_billing_date=next_billing_date,
                clear_next_billing_date=self._wgs_product_has_single_day_term(product),
            )
            if self._wgs_is_order_recognized_as_subscription(upsell_order):
                self._wgs_close_source_subscription_after_upgrade(
                    source_order=upsell_source_order,
                    new_subscription_start_date=contract_date,
                )
            else:
                _logger.warning(
                    'WGS POS: upsell order %s is not recognized as subscription; source %s was not closed.',
                    upsell_order.name,
                    upsell_source_order.name,
                )

            _logger.info(
                'Created subscription upsell order %s from POS order %s line %s (source=%s, recurring_total=%s, paid=%s, credit=%s)',
                upsell_order.name,
                self.pos_reference,
                line.id,
                upsell_source_order.name,
                recurring_total,
                paid_total,
                credit_from_pos,
            )
            return upsell_order

        sale_order_fields = self.env['sale.order']._fields
        sale_order_values = {
            'partner_id': self.partner_id.id,
            'origin': self.pos_reference or self.name,
            'client_order_ref': self.pos_reference or self.name,
            'company_id': self.company_id.id,
            'order_line': [Command.create(line_values)],
        }
        if 'date_order' in sale_order_fields:
            sale_order_values['date_order'] = self._wgs_convert_date_for_field_value(
                contract_date,
                sale_order_fields.get('date_order'),
            )
        self._wgs_assign_date_field(
            values=sale_order_values,
            fields_map=sale_order_fields,
            date_value=contract_date,
            preferred_field_names=('first_contract_date', 'contract_date', 'date_contract'),
        )
        if 'pricelist_id' in self._fields and self.pricelist_id:
            sale_order_values['pricelist_id'] = self.pricelist_id.id
        self._wgs_assign_date_field(
            values=sale_order_values,
            fields_map=sale_order_fields,
            date_value=sale_start_date,
            preferred_field_names=('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date'),
        )
        if subscription_end_date:
            self._wgs_assign_date_field(
                values=sale_order_values,
                fields_map=sale_order_fields,
                date_value=subscription_end_date,
                preferred_field_names=('end_date', 'date_end', 'subscription_end_date', 'recurring_end_date'),
            )
        if recurring_plan_id:
            for field_name in ('subscription_plan_id', 'plan_id', 'recurring_plan_id'):
                if field_name in sale_order_fields and field_name not in sale_order_values:
                    sale_order_values[field_name] = recurring_plan_id
            self._wgs_assign_many2one_value(
                values=sale_order_values,
                fields_map=sale_order_fields,
                value_id=recurring_plan_id,
                preferred_field_names=('subscription_plan_id', 'plan_id', 'recurring_plan_id'),
                comodel_checker=self._wgs_is_plan_model_name,
            )

        sale_order = self.env['sale.order'].create(sale_order_values)
        if 'participant_ids' in sale_order._fields:
            sale_order.write({'participant_ids': [Command.set(participant_ids)]})
            _logger.info(
                'WGS POS: participant_ids synced on sale order %s -> %s',
                sale_order.name,
                participant_ids,
            )

        sale_order_line = sale_order.order_line.filtered(lambda so_line: so_line.product_id == product)[:1]
        if not sale_order_line:
            sale_order_line = sale_order.order_line[:1]
        self._wgs_link_pos_and_sale_records(
            pos_line=line,
            sale_order=sale_order,
            sale_order_line=sale_order_line,
        )

        # Confirm immediately: POS payment is considered the paid period trigger.
        sale_order.action_confirm()
        self._wgs_sync_subscription_metadata(
            sale_order=sale_order,
            participant_ids=participant_ids,
            contract_date=contract_date,
            subscription_start_date=subscription_start_date,
            subscription_end_date=subscription_end_date,
            next_billing_date=next_billing_date,
            clear_next_billing_date=self._wgs_product_has_single_day_term(product),
        )

        _logger.info(
            'Created sale subscription order %s from POS order %s line %s',
            sale_order.name,
            self.pos_reference,
            line.id,
        )
        return sale_order

    def _wgs_find_active_subscription_for_partner(self, partner, company=False):
        partner.ensure_one()
        sale_order_model = self.env['sale.order']
        partner_ids = self._wgs_get_subscription_partner_scope_ids_for_pos(partner)

        candidates = sale_order_model.browse()
        # Prefer shared helper used by vigencias flow.
        helper = getattr(sale_order_model, '_get_pos_subscription_orders_by_partners', None)
        if callable(helper):
            partner_batch = self.env['res.partner'].browse(list(partner_ids)).exists()
            if partner_batch:
                mapped = helper(partner_batch) or {}
                for pid in partner_batch.ids:
                    candidates |= mapped.get(pid, sale_order_model.browse())

        domain = [('state', 'in', ['sale', 'done'])]
        if 'participant_ids' in sale_order_model._fields:
            domain.extend(
                [
                    '|',
                    ('partner_id', 'in', list(partner_ids)),
                    ('participant_ids', 'in', list(partner_ids)),
                ]
            )
        else:
            domain.append(('partner_id', 'in', list(partner_ids)))

        if company and 'company_id' in sale_order_model._fields:
            domain.append(('company_id', '=', company.id))
        direct_candidates = sale_order_model.search(domain, order='id desc', limit=500)
        candidates |= direct_candidates

        # Extra fallback: any order carrying subscription_state marker for related partners.
        if 'subscription_state' in sale_order_model._fields:
            state_domain = [('state', 'in', ['sale', 'done']), ('subscription_state', '!=', False)]
            if 'participant_ids' in sale_order_model._fields:
                state_domain.extend(
                    [
                        '|',
                        ('partner_id', 'in', list(partner_ids)),
                        ('participant_ids', 'in', list(partner_ids)),
                    ]
                )
            else:
                state_domain.append(('partner_id', 'in', list(partner_ids)))
            if company and 'company_id' in sale_order_model._fields:
                state_domain.append(('company_id', '=', company.id))
            candidates |= sale_order_model.search(state_domain, order='id desc', limit=200)

        if company and 'company_id' in sale_order_model._fields:
            candidates = candidates.filtered(lambda order: order.company_id.id == company.id)

        candidates = candidates.filtered(
            lambda order: self._wgs_order_has_subscription_signal(order) and self._wgs_is_subscription_order_active_for_upsell(order)
        )
        if not candidates:
            # Last-resort fallback for DBs where recurring markers are sparse but subscription_state is set.
            relaxed_candidates = direct_candidates.filtered(
                lambda order: self._wgs_order_has_subscription_state_value(order)
                and self._wgs_is_subscription_order_active_for_upsell(order)
            )
            candidates = relaxed_candidates
        if not candidates:
            _logger.info(
                'WGS POS: no active subscription source detected for partner %s (commercial=%s, partner_ids=%s)',
                partner.id,
                partner.commercial_partner_id.id if 'commercial_partner_id' in partner._fields and partner.commercial_partner_id else False,
                sorted(partner_ids),
            )
            return candidates

        direct_owner_candidates = candidates.filtered(lambda order: order.partner_id.id in partner_ids)
        return (direct_owner_candidates or candidates).sorted(key=lambda order: order.id, reverse=True)[:1]

    def _wgs_get_blocking_subscription_for_new_flow(self, partner, company=False):
        partner.ensure_one()
        candidate = self._wgs_find_active_subscription_for_partner(partner, company=company)[:1]
        return candidate.exists() if candidate else self.env['sale.order']

    def _wgs_get_blocking_subscription_for_new_flow_message(self, source_order):
        source_order.ensure_one()
        item = {}
        build_item = getattr(source_order, '_build_pos_subscription_status_item', None)
        if callable(build_item):
            try:
                item = build_item(fields.Date.context_today(self)) or {}
            except Exception:
                item = {}
        package_label = ', '.join(item.get('package_names') or []) or source_order.name or source_order.display_name
        return _(
            'El cliente ya tiene una membresía activa o por renovar (%(package)s). '
            'Por favor realiza un upsale o una renovación.'
        ) % {
            'package': package_label,
        }

    def _wgs_get_reenroll_source_for_new_same_product_flow(self, partner, product, company=False):
        partner = partner.exists()
        product = product.exists()
        if not partner or not product:
            return self.env['sale.order']

        candidates = self._wgs_find_closed_subscription_candidates_for_partner(
            partner,
            company=company,
        ).filtered(lambda order: self._wgs_subscription_order_has_product(order, product))
        if not candidates:
            return self.env['sale.order']

        partner_scope_ids = self._wgs_get_subscription_partner_scope_ids_for_pos(partner)
        direct_owner_candidates = candidates.filtered(lambda order: order.partner_id.id in partner_scope_ids)
        return (direct_owner_candidates or candidates).sorted(key=lambda order: order.id, reverse=True)[:1]

    def _wgs_get_reenroll_required_for_new_same_product_message(self, source_order, product):
        source_order.ensure_one()
        return _(
            'El cliente ya tiene una suscripción cerrada/cancelada del mismo paquete '
            '(%(package)s, %(subscription)s). Usa Reinscribir para reactivar ese paquete, '
            'o elige un paquete diferente para una nueva inscripción.'
        ) % {
            'package': product.display_name,
            'subscription': source_order.name or source_order.display_name,
        }

    def _wgs_find_closed_subscription_candidates_for_partner(self, partner, company=False):
        partner.ensure_one()
        sale_order_model = self.env['sale.order']
        partner_scope_ids = self._wgs_get_subscription_partner_scope_ids_for_pos(partner)
        if not partner_scope_ids:
            return sale_order_model

        domain = [('state', 'in', ['sale', 'done'])]
        if 'participant_ids' in sale_order_model._fields:
            domain.extend([
                '|',
                ('partner_id', 'in', list(partner_scope_ids)),
                ('participant_ids', 'in', list(partner_scope_ids)),
            ])
        else:
            domain.append(('partner_id', 'in', list(partner_scope_ids)))
        if company and 'company_id' in sale_order_model._fields:
            domain.append(('company_id', '=', company.id))

        candidates = sale_order_model.search(domain, order='id desc', limit=500)
        return candidates.filtered(
            lambda order: self._wgs_order_has_subscription_signal(order)
            and self._wgs_is_subscription_order_closed_for_reenroll(order)
        )

    def _wgs_get_subscription_partner_scope_ids_for_pos(self, partner):
        partner.ensure_one()
        partner_ids = {partner.id}
        if 'commercial_partner_id' in partner._fields and partner.commercial_partner_id:
            commercial_partner = partner.commercial_partner_id
            partner_ids.add(commercial_partner.id)
            if 'child_ids' in commercial_partner._fields:
                partner_ids.update(commercial_partner.child_ids.ids)
        return partner_ids

    def _wgs_find_partner_active_subscription_for_upsell(self):
        self.ensure_one()
        if not self.partner_id:
            return False
        candidate = self._wgs_find_active_subscription_for_partner(self.partner_id)
        if not candidate:
            return False

        all_candidates = self.env['sale.order'].search(
            [('partner_id', '=', self.partner_id.id), ('state', 'in', ['sale', 'done'])],
            order='id desc',
            limit=25,
        ).filtered(
            lambda order: self._wgs_order_has_subscription_signal(order) and self._wgs_is_subscription_order_active_for_upsell(order)
        )
        if len(all_candidates) > 1:
            _logger.warning(
                'WGS POS: multiple active subscriptions for partner %s. Using most recent %s',
                self.partner_id.id,
                candidate.name,
            )
        return candidate

    def _wgs_order_has_subscription_signal(self, sale_order):
        sale_order.ensure_one()
        check_method = getattr(sale_order, '_is_subscription_record_for_pos', None)
        if callable(check_method):
            try:
                return bool(check_method())
            except Exception as error:
                _logger.warning(
                    'WGS POS: failed to evaluate _is_subscription_record_for_pos on %s (%s). Falling back.',
                    sale_order.name,
                    error,
                )

        # 1) Standard recurring line flag
        if sale_order.order_line.filtered(lambda so_line: self._wgs_is_recurring_so_line(so_line)):
            return True

        # 2) Subscription state marker
        if 'subscription_state' in sale_order._fields:
            state_value = (sale_order.subscription_state or '').strip()
            if state_value:
                return True

        # 3) Next invoice marker
        for field_name in ('recurring_next_date', 'next_invoice_date'):
            if field_name in sale_order._fields and sale_order[field_name]:
                return True

        # 4) Plan marker
        for field_name in ('plan_id', 'subscription_plan_id', 'recurring_plan_id'):
            if field_name in sale_order._fields and sale_order[field_name]:
                return True

        return False

    def _wgs_is_subscription_order_active_for_upsell(self, sale_order):
        sale_order.ensure_one()
        if 'subscription_state' not in sale_order._fields:
            return True
        state_value = (sale_order.subscription_state or '').lower()
        if not state_value:
            return True
        return not any(token in state_value for token in self._WGS_INVALID_SUBSCRIPTION_STATE_TOKENS)

    def _wgs_is_subscription_order_closed_for_reenroll(self, sale_order):
        sale_order.ensure_one()
        if 'subscription_state' not in sale_order._fields:
            return False
        state_value = (sale_order.subscription_state or '').strip().lower()
        if not state_value:
            return False
        return any(token in state_value for token in ('cancel', 'canceled', 'cancelled', 'close', 'closed', 'churn', 'churned'))

    def _wgs_subscription_order_has_product(self, sale_order, product):
        sale_order.ensure_one()
        product = product.exists()
        if not product:
            return False

        product_tmpl = product.product_tmpl_id
        recurring_lines = sale_order.order_line.filtered(lambda so_line: self._wgs_is_recurring_so_line(so_line))
        for line in recurring_lines:
            line_product = line.product_id
            if line_product == product:
                return True
            if product_tmpl and line_product.product_tmpl_id == product_tmpl:
                return True
        return False

    def _wgs_build_subscription_recurring_charge_payload(
        self,
        source_order,
        *,
        product_id=False,
        preferred_plan_id=False,
        preferred_pricing_id=False,
        is_renewal=False,
        is_reenroll=False,
    ):
        source_order.ensure_one()
        snapshot = self._wgs_resolve_subscription_pricing_snapshot(
            flow='renewal' if is_renewal else 'reenroll' if is_reenroll else 'renewal',
            source_order=source_order,
            product=self._wgs_browse_product_for_pos(product_id) if product_id else False,
            preferred_plan_id=preferred_plan_id,
            preferred_pricing_id=preferred_pricing_id,
        )

        return {
            'charge_now': float(snapshot.get('charge_now') or 0.0),
            'credit_amount': 0.0,
            'recurring_price': float(snapshot.get('price_unit') or 0.0),
            'ticket_charge_now': float(snapshot.get('ticket_charge_now') or 0.0),
            'ticket_credit_amount': 0.0,
            'ticket_recurring_price': float(snapshot.get('ticket_price_unit') or 0.0),
            'display_charge_now': float(snapshot.get('display_charge_now') or 0.0),
            'display_credit_amount': 0.0,
            'display_recurring_price': float(snapshot.get('display_price_unit') or 0.0),
            'plan_id': snapshot.get('plan_id') or False,
            'plan_name': snapshot.get('plan_name') or False,
            'pricing_id': snapshot.get('pricing_id') or False,
            'interval_label': snapshot.get('interval_label') or '',
            'interval_value': int(snapshot.get('interval_value') or 1),
            'interval_unit': snapshot.get('interval_unit') or 'month',
            'is_upgrade': False,
            'is_renewal': bool(is_renewal),
            'is_reenroll': bool(is_reenroll),
            'source_subscription_id': source_order.id,
            'source_subscription_name': source_order.name,
        }

    def _wgs_is_order_recognized_as_subscription(self, sale_order):
        sale_order.ensure_one()
        check_method = getattr(sale_order, '_is_subscription_record_for_pos', None)
        if callable(check_method):
            try:
                return bool(check_method())
            except Exception as error:
                _logger.warning(
                    'WGS POS: failed to evaluate _is_subscription_record_for_pos on %s (%s). Falling back.',
                    sale_order.name,
                    error,
                )

        if not sale_order.order_line.filtered(lambda so_line: self._wgs_is_recurring_so_line(so_line)):
            return False

        if 'plan_id' in sale_order._fields and sale_order.plan_id:
            return True
        if 'subscription_state' in sale_order._fields and (sale_order.subscription_state or '').strip():
            return True
        for field_name in ('recurring_next_date', 'next_invoice_date'):
            if field_name in sale_order._fields and sale_order[field_name]:
                return True
        return False

    def _wgs_order_has_subscription_state_value(self, sale_order):
        sale_order.ensure_one()
        if 'subscription_state' not in sale_order._fields:
            return False
        state_value = (sale_order.subscription_state or '').strip()
        return bool(state_value)

    def _wgs_create_subscription_upsell_sale_order_from_line(self, source_order, line_values, credit_amount=0.0):
        self.ensure_one()
        source_order.ensure_one()

        upsell_order = self._wgs_get_or_create_subscription_upsell_order(source_order)
        if not upsell_order:
            raise UserError(
                _(
                    'No se pudo generar una cotización de Upsell para la suscripción %(subscription)s.'
                ) % {'subscription': source_order.display_name}
            )
        if upsell_order.state not in ('draft', 'sent'):
            raise UserError(
                _(
                    'La cotización de Upsell %(order)s no está en borrador.'
                ) % {'order': upsell_order.display_name}
            )

        write_values = {}
        if 'origin' in upsell_order._fields:
            write_values['origin'] = self.pos_reference or self.name
        if 'client_order_ref' in upsell_order._fields:
            write_values['client_order_ref'] = self.pos_reference or self.name
        if 'pricelist_id' in self._fields and self.pricelist_id and 'pricelist_id' in upsell_order._fields:
            write_values['pricelist_id'] = self.pricelist_id.id
        if write_values:
            upsell_order.write(write_values)

        # Replace default lines generated by upsell action with POS-selected target package.
        if upsell_order.order_line:
            upsell_order.order_line.unlink()

        line_commands = [Command.create(line_values)]
        self._wgs_apply_upsell_order_lines(
            upsell_order=upsell_order,
            line_values=line_values,
            credit_amount=credit_amount,
        )

        return upsell_order

    def _wgs_apply_upsell_order_lines(self, upsell_order, line_values, credit_amount=0.0):
        upsell_order.ensure_one()
        if upsell_order.order_line:
            upsell_order.order_line.unlink()

        line_commands = [Command.create(line_values)]
        bonus_line_values = self._wgs_build_upgrade_bonus_line_values(credit_amount=credit_amount)
        if bonus_line_values:
            line_commands.append(Command.create(bonus_line_values))
        upsell_order.write({'order_line': line_commands})

        recurring_plan_id = int(
            line_values.get('subscription_plan_id')
            or line_values.get('plan_id')
            or line_values.get('recurring_plan_id')
            or 0
        )
        if recurring_plan_id > 0:
            order_values = {}
            self._wgs_assign_many2one_value(
                values=order_values,
                fields_map=upsell_order._fields,
                value_id=recurring_plan_id,
                preferred_field_names=('plan_id', 'subscription_plan_id', 'recurring_plan_id'),
                comodel_checker=self._wgs_is_plan_model_name,
            )
            if order_values:
                upsell_order.write(order_values)

        return upsell_order

    def _wgs_build_upgrade_bonus_line_values(self, credit_amount=0.0):
        credit_amount = float(credit_amount or 0.0)
        if credit_amount <= 0.0:
            return False

        product = self._wgs_get_upgrade_credit_product()
        if not product:
            return False

        line_fields = self.env['sale.order.line']._fields
        values = {'product_id': product.id}
        if 'name' in line_fields:
            values['name'] = _('Bonificación upgrade de plan')

        qty_field_name = next(
            (
                field_name
                for field_name in ('product_uom_qty', 'quantity', 'qty')
                if field_name in line_fields
            ),
            False,
        )
        if qty_field_name:
            values[qty_field_name] = 1

        uom_field_name = next(
            (
                field_name
                for field_name in ('product_uom_id', 'product_uom', 'uom_id')
                if field_name in line_fields
            ),
            False,
        )
        if uom_field_name and product.uom_id:
            values[uom_field_name] = product.uom_id.id

        if 'price_unit' in line_fields:
            values['price_unit'] = -abs(credit_amount)
        if 'discount' in line_fields:
            values['discount'] = 0
        return values

    def _wgs_get_upgrade_credit_product(self):
        product_model = self.env['product.product'].sudo()
        default_code = 'WGS_UPGRADE_CREDIT'
        product = product_model.search([('default_code', '=', default_code)], limit=1)
        if product:
            return product

        values = {
            'name': 'Bonificación Upgrade WGS',
            'default_code': default_code,
            'sale_ok': True,
            'purchase_ok': False,
            'list_price': 0.0,
        }
        if 'detailed_type' in product_model._fields:
            values['detailed_type'] = 'service'
        elif 'type' in product_model._fields:
            values['type'] = 'service'
        if 'recurring_invoice' in product_model._fields:
            values['recurring_invoice'] = False
        return product_model.create(values)

    def _wgs_get_or_create_subscription_upsell_order(self, source_order):
        source_order.ensure_one()

        method_names = (
            'action_upsell',
            'action_subscription_upsell',
            'action_subscription_create_upsell',
        )
        for method_name in method_names:
            method = getattr(source_order, method_name, None)
            if not callable(method):
                continue
            try:
                result = method()
            except Exception as error:
                _logger.warning(
                    'WGS POS: upsell method %s failed on %s (%s)',
                    method_name,
                    source_order.name,
                    error,
                )
                continue

            upsell_order = self._wgs_extract_sale_order_from_upsell_result(result, source_order)
            if upsell_order:
                return upsell_order

        upsell_order = self._wgs_find_recent_subscription_upsell_order(source_order)
        if upsell_order:
            return upsell_order

        # Final fallback: create a draft SO linked to source subscription so POS flow can continue.
        return self._wgs_create_manual_subscription_upsell_order(source_order)

    def _wgs_create_manual_subscription_upsell_order(self, source_order):
        source_order.ensure_one()
        sale_order_model = self.env['sale.order']
        sale_order_fields = sale_order_model._fields

        values = {
            'partner_id': source_order.partner_id.id or self.partner_id.id,
            'company_id': source_order.company_id.id or self.company_id.id,
        }

        if 'origin' in sale_order_fields:
            values['origin'] = self.pos_reference or self.name or source_order.name
        if 'client_order_ref' in sale_order_fields:
            values['client_order_ref'] = self.pos_reference or self.name or source_order.name
        if 'pricelist_id' in sale_order_fields:
            if 'pricelist_id' in self._fields and self.pricelist_id:
                values['pricelist_id'] = self.pricelist_id.id
            elif 'pricelist_id' in source_order._fields and source_order.pricelist_id:
                values['pricelist_id'] = source_order.pricelist_id.id
        if 'user_id' in sale_order_fields and source_order.user_id:
            values['user_id'] = source_order.user_id.id
        if 'team_id' in sale_order_fields and 'team_id' in source_order._fields and source_order.team_id:
            values['team_id'] = source_order.team_id.id
        if 'payment_term_id' in sale_order_fields and 'payment_term_id' in source_order._fields and source_order.payment_term_id:
            values['payment_term_id'] = source_order.payment_term_id.id
        if 'fiscal_position_id' in sale_order_fields and 'fiscal_position_id' in source_order._fields and source_order.fiscal_position_id:
            values['fiscal_position_id'] = source_order.fiscal_position_id.id

        # Link to source subscription/order using the best matching relation field.
        self._wgs_assign_many2one_by_model(
            values=values,
            fields_map=sale_order_fields,
            value_id=source_order.id,
            model_name='sale.order',
            preferred_field_names=('subscription_id', 'origin_order_id', 'note_order'),
            required_name_tokens=('subscription',),
        )

        upsell_order = sale_order_model.create(values)
        _logger.info(
            'WGS POS: manual upsell draft created %s for source subscription %s',
            upsell_order.name,
            source_order.name,
        )
        return upsell_order

    def _wgs_extract_sale_order_from_upsell_result(self, result, source_order):
        if not result:
            return self.env['sale.order']

        if isinstance(result, models.BaseModel):
            if result._name == 'sale.order':
                return result.exists()[:1]
            return self.env['sale.order']

        if isinstance(result, int):
            return self.env['sale.order'].browse(int(result)).exists()[:1]

        if isinstance(result, dict):
            res_model = result.get('res_model')
            res_id = result.get('res_id')
            if res_model == 'sale.order' and res_id:
                return self.env['sale.order'].browse(int(res_id)).exists()[:1]

            context = result.get('context') or {}
            default_res_id = context.get('default_subscription_id') or context.get('default_origin_order_id')
            if default_res_id and int(default_res_id) != source_order.id:
                candidate = self.env['sale.order'].browse(int(default_res_id)).exists()
                if candidate:
                    return candidate[:1]

        return self.env['sale.order']

    def _wgs_find_recent_subscription_upsell_order(self, source_order):
        source_order.ensure_one()
        sale_order_model = self.env['sale.order']

        preferred_relation_fields = (
            'subscription_id',
            'origin_order_id',
            'note_order',
        )
        for field_name in preferred_relation_fields:
            field = sale_order_model._fields.get(field_name)
            if not field or field.type != 'many2one' or getattr(field, 'comodel_name', '') != 'sale.order':
                continue
            upsell_order = sale_order_model.search(
                [
                    (field_name, '=', source_order.id),
                    ('state', 'in', ['draft', 'sent']),
                ],
                order='id desc',
                limit=1,
            )
            if upsell_order:
                return upsell_order

        for field_name, field in sale_order_model._fields.items():
            if field.type != 'many2one' or getattr(field, 'comodel_name', '') != 'sale.order':
                continue
            normalized_name = (field_name or '').lower()
            if not any(token in normalized_name for token in ('subscription', 'origin', 'upsell', 'note')):
                continue
            upsell_order = sale_order_model.search(
                [
                    (field_name, '=', source_order.id),
                    ('state', 'in', ['draft', 'sent']),
                ],
                order='id desc',
                limit=1,
            )
            if upsell_order:
                return upsell_order

        return sale_order_model.browse()

    def _wgs_close_source_subscription_after_upgrade(self, source_order, new_subscription_start_date):
        source_order.ensure_one()

        close_date = fields.Date.to_date(new_subscription_start_date) or fields.Date.context_today(self)
        close_date = close_date - timedelta(days=1)
        values = {}
        end_field = self._wgs_find_subscription_end_date_field(source_order)
        if end_field:
            values[end_field] = close_date
        if values:
            source_order.write(values)

        for method_name in ('action_close', 'action_subscription_close', 'set_close'):
            method = getattr(source_order, method_name, None)
            if not callable(method):
                continue
            try:
                method()
                _logger.info(
                    'WGS POS: source subscription %s closed after upgrade with %s',
                    source_order.name,
                    method_name,
                )
                return
            except Exception as error:
                _logger.warning(
                    'WGS POS: could not execute %s on source subscription %s (%s)',
                    method_name,
                    source_order.name,
                    error,
                )

    def _wgs_get_upsale_schedule_from_source(self, source_order, today=False):
        source_order.ensure_one()

        sale_start_date = fields.Date.to_date(today) or fields.Date.context_today(self)
        subscription_start_date = self._wgs_get_first_date_from_order(
            source_order,
            ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date', 'recurring_start_date', 'date_order'),
        )
        _period_start, period_end = self._wgs_get_current_subscription_period_bounds(
            source_order,
            today=sale_start_date,
        )
        next_billing_date = self._wgs_get_first_date_from_order(
            source_order,
            ('recurring_next_date', 'next_invoice_date'),
        ) or period_end
        subscription_end_date = self._wgs_get_first_date_from_order(
            source_order,
            ('end_date', 'date_end', 'subscription_end_date', 'recurring_end_date'),
        )
        if not subscription_end_date and next_billing_date:
            subscription_end_date = next_billing_date - timedelta(days=1)

        return {
            'sale_start_date': sale_start_date,
            'subscription_start_date': subscription_start_date or sale_start_date,
            'subscription_end_date': subscription_end_date,
            'next_billing_date': next_billing_date,
        }

    def _wgs_link_pos_and_sale_records(self, pos_line, sale_order, sale_order_line=False):
        self.ensure_one()
        if not pos_line or not sale_order:
            return

        pos_line_values = {}
        self._wgs_assign_many2one_by_model(
            values=pos_line_values,
            fields_map=pos_line._fields,
            value_id=sale_order.id,
            model_name='sale.order',
            preferred_field_names=('sale_order_id', 'sale_order_origin_id', 'origin_sale_order_id'),
            required_name_tokens=('sale', 'order'),
        )
        if sale_order_line:
            self._wgs_assign_many2one_by_model(
                values=pos_line_values,
                fields_map=pos_line._fields,
                value_id=sale_order_line.id,
                model_name='sale.order.line',
                preferred_field_names=('sale_order_line_id', 'sale_order_origin_id', 'origin_sale_order_line_id'),
                required_name_tokens=('sale', 'line'),
            )
        if pos_line_values:
            pos_line.write(pos_line_values)

        sale_order_values = {}
        self._wgs_assign_many2one_by_model(
            values=sale_order_values,
            fields_map=sale_order._fields,
            value_id=self.id,
            model_name='pos.order',
            preferred_field_names=('pos_order_id', 'origin_pos_order_id'),
            required_name_tokens=('pos', 'order'),
        )
        if sale_order_values:
            sale_order.write(sale_order_values)

        if pos_line_values or sale_order_values:
            _logger.info(
                'WGS POS: linked POS/Sale records for pos.order %s line %s and sale.order %s line %s',
                self.pos_reference,
                pos_line.id,
                sale_order.name,
                sale_order_line.id if sale_order_line else False,
            )

    def _wgs_sync_subscription_metadata(
        self,
        sale_order,
        participant_ids,
        contract_date=False,
        subscription_start_date=False,
        subscription_end_date=False,
        next_billing_date=False,
        clear_next_billing_date=False,
    ):
        target_orders = self._wgs_get_subscription_orders_from_base(sale_order)
        for target_order in target_orders:
            values = {}
            participant_field = self._wgs_find_partner_multi_field(target_order)
            if participant_field:
                values[participant_field] = [Command.set(participant_ids)]
            if contract_date:
                contract_field = self._wgs_find_subscription_contract_date_field(target_order)
                if contract_field:
                    values[contract_field] = self._wgs_convert_date_for_field_value(
                        contract_date,
                        target_order._fields.get(contract_field),
                    )
                if 'date_order' in target_order._fields and 'date_order' not in values:
                    values['date_order'] = self._wgs_convert_date_for_field_value(
                        contract_date,
                        target_order._fields.get('date_order'),
                    )
            if subscription_start_date:
                start_field = self._wgs_find_subscription_start_date_field(target_order)
                if start_field:
                    values[start_field] = subscription_start_date
            if subscription_end_date:
                end_field = self._wgs_find_subscription_end_date_field(target_order)
                if end_field:
                    values[end_field] = subscription_end_date
            if next_billing_date:
                next_field = self._wgs_find_subscription_next_invoice_date_field(target_order)
                if next_field:
                    values[next_field] = next_billing_date
            elif clear_next_billing_date:
                next_field = self._wgs_find_subscription_next_invoice_date_field(target_order)
                if next_field:
                    values[next_field] = False
            if values:
                target_order.write(values)
                _logger.info(
                    'WGS POS: synced metadata on subscription order %s (participants=%s contract_date=%s start_date=%s end_date=%s next=%s)',
                    target_order.name,
                    participant_ids,
                    contract_date or False,
                    subscription_start_date or False,
                    subscription_end_date or False,
                    next_billing_date or False,
                )

    def _wgs_get_subscription_orders_from_base(self, sale_order):
        orders = sale_order
        fields_map = sale_order._fields

        for field_name, field in fields_map.items():
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
            lambda order: bool(
                order.order_line.filtered(
                    lambda line: line.product_id and line.product_id.product_tmpl_id.recurring_invoice
                )
            )
        )
        return recurring_orders or sale_order

    def _wgs_find_partner_multi_field(self, sale_order):
        fields_map = sale_order._fields
        field = fields_map.get('participant_ids')
        if field and field.type in ('many2many', 'one2many') and getattr(field, 'comodel_name', '') == 'res.partner':
            return 'participant_ids'

        for field_name, field in fields_map.items():
            if field.type not in ('many2many', 'one2many'):
                continue
            if getattr(field, 'comodel_name', '') != 'res.partner':
                continue
            normalized_name = (field_name or '').lower()
            if any(token in normalized_name for token in ('participant', 'member', 'attendee')):
                return field_name
        return False

    def _wgs_convert_date_for_field_value(self, date_value, field):
        date_value = fields.Date.to_date(date_value)
        if not date_value:
            return False
        if field and field.type == 'datetime':
            return fields.Datetime.to_datetime(date_value)
        return date_value

    def _wgs_find_subscription_end_date_field(self, sale_order):
        fields_map = sale_order._fields
        preferred = ('end_date', 'date_end', 'subscription_end_date', 'recurring_end_date')
        for field_name in preferred:
            field = fields_map.get(field_name)
            if field and field.type in ('date', 'datetime'):
                return field_name

        for field_name, field in fields_map.items():
            if field.type not in ('date', 'datetime'):
                continue
            normalized_name = (field_name or '').lower()
            if any(token in normalized_name for token in ('end', 'until', 'close')) and any(
                token in normalized_name for token in ('subscription', 'recurr', 'period')
            ):
                return field_name
        return False

    def _wgs_find_subscription_start_date_field(self, sale_order):
        fields_map = sale_order._fields
        preferred = ('wgs_effective_start_date', 'start_date', 'date_start', 'subscription_start_date', 'recurring_start_date')
        for field_name in preferred:
            field = fields_map.get(field_name)
            if field and field.type in ('date', 'datetime'):
                return field_name

        for field_name, field in fields_map.items():
            if field.type not in ('date', 'datetime'):
                continue
            normalized_name = (field_name or '').lower()
            if any(token in normalized_name for token in ('start', 'begin', 'from')) and any(
                token in normalized_name for token in ('subscription', 'recurr', 'period')
            ):
                return field_name
        return False

    def _wgs_find_subscription_contract_date_field(self, sale_order):
        fields_map = sale_order._fields
        preferred = ('first_contract_date', 'contract_date', 'date_contract')
        for field_name in preferred:
            field = fields_map.get(field_name)
            if field and field.type in ('date', 'datetime'):
                return field_name

        for field_name, field in fields_map.items():
            if field.type not in ('date', 'datetime'):
                continue
            normalized_name = (field_name or '').lower()
            if any(token in normalized_name for token in ('contract', 'agreement')):
                return field_name
        return False

    def _wgs_find_subscription_next_invoice_date_field(self, sale_order):
        fields_map = sale_order._fields
        preferred = ('recurring_next_date', 'next_invoice_date', 'recurring_next_invoice_date')
        for field_name in preferred:
            field = fields_map.get(field_name)
            if field and field.type in ('date', 'datetime'):
                return field_name

        for field_name, field in fields_map.items():
            if field.type not in ('date', 'datetime'):
                continue
            normalized_name = (field_name or '').lower()
            if all(token in normalized_name for token in ('next', 'date')) and any(
                token in normalized_name for token in ('invoice', 'recurr', 'subscription')
            ):
                return field_name
        return False

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
            )
            if comodel_checker(getattr(field, 'comodel_name', '')) or heuristic_name_match:
                values[field_name] = value_id
                return

    def _wgs_assign_many2one_by_model(
        self,
        values,
        fields_map,
        value_id,
        model_name,
        preferred_field_names=(),
        required_name_tokens=(),
    ):
        value_id = int(value_id or 0)
        model_name = (model_name or '').strip()
        if value_id <= 0 or not model_name:
            return

        for field_name in preferred_field_names:
            field = fields_map.get(field_name)
            if field and field.type == 'many2one' and getattr(field, 'comodel_name', '') == model_name:
                values[field_name] = value_id
                return

        fallback_field_name = False
        tokens = tuple(token.lower() for token in (required_name_tokens or ()) if token)
        for field_name, field in fields_map.items():
            if field.type != 'many2one':
                continue
            if getattr(field, 'comodel_name', '') != model_name:
                continue
            if not fallback_field_name:
                fallback_field_name = field_name
            normalized_name = (field_name or '').lower()
            if tokens and all(token in normalized_name for token in tokens):
                values[field_name] = value_id
                return

        if fallback_field_name:
            values[fallback_field_name] = value_id

    def _wgs_assign_date_field(self, values, fields_map, date_value, preferred_field_names=()):
        if not date_value:
            return
        for field_name in preferred_field_names:
            if field_name in fields_map:
                values[field_name] = date_value
                return

    def _wgs_cancel_subscription_from_refund_line(self, line):
        self.ensure_one()

        original_line = None
        if 'refunded_orderline_id' in line._fields:
            original_line = line.refunded_orderline_id
        if not original_line and line.wgs_subscription_refund_origin_line_id:
            original_line = line.wgs_subscription_refund_origin_line_id

        sale_order = original_line.wgs_sale_order_id if original_line else line.wgs_sale_order_id
        original_flow = original_line.wgs_subscription_flow if original_line else line.wgs_subscription_flow

        if not sale_order:
            return
        if (
            original_flow in ('renewal', 'pending_charge')
            and line.wgs_subscription_flow != 'cancellation_refund'
        ):
            # Renewal/pending-charge refunds should not cancel the underlying subscription contract.
            line.wgs_sale_order_id = sale_order.id
            return

        if sale_order.state == 'cancel':
            line.wgs_sale_order_id = sale_order.id
            return

        sale_order.action_cancel()
        line.wgs_sale_order_id = sale_order.id

        _logger.info(
            'Cancelled sale subscription order %s from POS refund order %s line %s',
            sale_order.name,
            self.pos_reference,
            line.id,
        )

    def _wgs_get_refundable_pos_line_for_subscription(self, source_order):
        self.ensure_one()
        source_order.ensure_one()

        pos_line_model = self.env['pos.order.line'].sudo()
        candidates = self._wgs_get_pos_lines_linked_to_subscription(source_order).filtered(
            lambda line: float(line.qty or 0.0) > 0.0
        ).sorted(key=lambda line: line.id, reverse=True)
        if not candidates:
            return pos_line_model

        for candidate in candidates:
            refunded_lines = pos_line_model.browse()
            if 'refunded_orderline_id' in pos_line_model._fields:
                refunded_lines |= pos_line_model.search([('refunded_orderline_id', '=', candidate.id)])
            refunded_lines |= pos_line_model.search([('wgs_subscription_refund_origin_line_id', '=', candidate.id)])
            refunded_qty = sum(abs(float(refund_line.qty or 0.0)) for refund_line in refunded_lines if float(refund_line.qty or 0.0) < 0.0)
            original_qty = abs(float(candidate.qty or 0.0))
            if refunded_qty + 0.00001 < original_qty:
                return candidate
        return pos_line_model

    def _wgs_get_pos_lines_linked_to_subscription(self, source_order):
        self.ensure_one()
        source_order.ensure_one()

        pos_line_model = self.env['pos.order.line'].sudo()
        candidates = pos_line_model.search([('wgs_sale_order_id', '=', source_order.id)])

        fields_map = pos_line_model._fields
        generic_field_names = []
        for field_name, field in fields_map.items():
            if field.type != 'many2one':
                continue
            if getattr(field, 'comodel_name', '') != 'sale.order':
                continue
            if field_name == 'wgs_sale_order_id':
                continue
            generic_field_names.append(field_name)

        for field_name in generic_field_names:
            candidates |= pos_line_model.search([(field_name, '=', source_order.id)])

        if not candidates:
            return pos_line_model

        return candidates.exists()

    def _wgs_get_pos_line_total_amount(self, line, include_taxes=False):
        line.ensure_one()
        if include_taxes:
            for field_name in ('price_subtotal_incl', 'price_total', 'price_total_incl'):
                if field_name in line._fields:
                    return abs(float(line[field_name] or 0.0))
        for field_name in ('price_subtotal', 'price_total'):
            if field_name in line._fields:
                return abs(float(line[field_name] or 0.0))
        return abs(float(line.price_unit or 0.0) * float(line.qty or 0.0))

    def action_pos_order_cancel(self):
        super_method = getattr(super(), 'action_pos_order_cancel', None)
        result = super_method() if super_method else True
        for order in self:
            sale_orders = order.lines.filtered(
                lambda line: line.wgs_subscription_flow not in ('renewal', 'pending_charge')
            ).mapped('wgs_sale_order_id').filtered(lambda so: so and so.state != 'cancel')
            for sale_order in sale_orders:
                sale_order.action_cancel()
        return result
