import logging
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)


class WgsPosAuthorizationCredential(models.Model):
    _name = 'wgs.pos.authorization.credential'
    _description = 'Credencial de autorización POS WGS'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one('hr.employee', required=True, index=True, ondelete='cascade')
    authorization_pin = fields.Char(required=True, index=True, copy=False)
    last_rotated_at = fields.Datetime(copy=False, readonly=True)

    _employee_uniq = models.Constraint(
        'unique(employee_id)',
        'Cada empleado sólo puede tener una credencial de autorización WGS.',
    )
    _authorization_pin_uniq = models.Constraint(
        'unique(authorization_pin)',
        'El PIN de autorización WGS ya está asignado a otro empleado.',
    )

    @api.constrains('employee_id', 'authorization_pin')
    def _check_authorization_pin(self):
        for credential in self:
            pin = str(credential.authorization_pin or '').strip()
            if not pin:
                raise ValidationError(_('El PIN de autorización WGS no puede estar vacío.'))
            employee = credential.employee_id
            pos_pin = str(employee.pin or '').strip() if employee and 'pin' in employee._fields else ''
            if pos_pin and pin == pos_pin:
                raise ValidationError(_('El PIN de autorización WGS debe ser diferente al PIN de acceso POS.'))


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    wgs_authorization_pin = fields.Char(
        string='PIN autorización WGS',
        compute='_compute_wgs_authorization_credential_fields',
        inverse='_inverse_wgs_authorization_pin',
        search='_search_wgs_authorization_pin',
        copy=False,
        groups='hr.group_hr_manager',
        help='PIN independiente del PIN nativo del POS. Se usa para autorizar descuentos y paquetes desde Suscripciones POS.',
    )
    wgs_authorization_pin_last_rotated_at = fields.Datetime(
        string='Última rotación PIN autorización WGS',
        compute='_compute_wgs_authorization_credential_fields',
        copy=False,
        readonly=True,
        groups='hr.group_hr_manager',
    )

    def _wgs_authorization_credentials(self):
        Credential = self.env['wgs.pos.authorization.credential'].sudo()
        return Credential.search([('employee_id', 'in', self.ids)]) if self else Credential.browse()

    def _wgs_authorization_credential(self):
        self.ensure_one()
        return self.env['wgs.pos.authorization.credential'].sudo().search([('employee_id', '=', self.id)], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        pins = []
        normalized_vals_list = []
        for vals in vals_list:
            values = dict(vals or {})
            pins.append(values.pop('wgs_authorization_pin', False))
            values.pop('wgs_authorization_pin_last_rotated_at', None)
            normalized_vals_list.append(values)
        employees = super().create(normalized_vals_list)
        for employee, pin in zip(employees, pins):
            if pin:
                employee._wgs_set_authorization_pin(pin, fields.Datetime.now())
        return employees

    def write(self, vals):
        values = dict(vals or {})
        has_authorization_pin = 'wgs_authorization_pin' in values
        authorization_pin = values.pop('wgs_authorization_pin', False)
        values.pop('wgs_authorization_pin_last_rotated_at', None)
        result = super().write(values)
        if has_authorization_pin:
            rotated_at = fields.Datetime.now() if authorization_pin else False
            for employee in self:
                employee._wgs_set_authorization_pin(authorization_pin, rotated_at)
        return result

    def _wgs_set_authorization_pin(self, pin, rotated_at=False):
        self.ensure_one()
        Credential = self.env['wgs.pos.authorization.credential'].sudo()
        normalized_pin = str(pin or '').strip()
        credential = self._wgs_authorization_credential()
        if not normalized_pin:
            if credential:
                credential.unlink()
            return False
        values = {
            'employee_id': self.id,
            'authorization_pin': normalized_pin,
            'last_rotated_at': rotated_at or fields.Datetime.now(),
        }
        if credential:
            credential.write(values)
        else:
            credential = Credential.create(values)
        return credential

    @api.depends('pin')
    def _compute_wgs_authorization_credential_fields(self):
        credentials_by_employee = {
            credential.employee_id.id: credential
            for credential in self._wgs_authorization_credentials()
        }
        for employee in self:
            credential = credentials_by_employee.get(employee.id)
            employee.wgs_authorization_pin = credential.authorization_pin if credential else False
            employee.wgs_authorization_pin_last_rotated_at = credential.last_rotated_at if credential else False

    def _inverse_wgs_authorization_pin(self):
        now = fields.Datetime.now()
        for employee in self:
            employee._wgs_set_authorization_pin(employee.wgs_authorization_pin, now if employee.wgs_authorization_pin else False)

    @api.model
    def _search_wgs_authorization_pin(self, operator, value):
        if operator not in ('=', '!='):
            raise NotImplementedError(_('Sólo se soporta buscar PIN de autorización por igualdad.'))
        pin = str(value or '').strip()
        Credential = self.env['wgs.pos.authorization.credential'].sudo()
        credentials = Credential.search([('authorization_pin', '=', pin)]) if pin else Credential.browse()
        employee_ids = credentials.mapped('employee_id').ids
        if operator == '=':
            return [('id', 'in', employee_ids or [0])]
        return [('id', 'not in', employee_ids)]

    @api.constrains('pin')
    def _check_wgs_authorization_pin_differs_from_pos_pin(self):
        for employee in self:
            credential = employee._wgs_authorization_credential()
            if not credential:
                continue
            pos_pin = str(employee.pin or '').strip() if 'pin' in employee._fields else ''
            if pos_pin and credential.authorization_pin == pos_pin:
                raise ValidationError(_('El PIN de autorización WGS debe ser diferente al PIN de acceso POS.'))

    @api.model
    def _wgs_find_by_authorization_pin(self, authorization_pin):
        pin = str(authorization_pin or '').strip()
        if not pin:
            return self.browse()
        credential = self.env['wgs.pos.authorization.credential'].sudo().search(
            [('authorization_pin', '=', pin)],
            limit=1,
        )
        return credential.employee_id.with_context(active_test=False) if credential else self.browse()

    @api.model
    def _wgs_authorization_pin_rotation_days(self):
        raw_value = self.env['ir.config_parameter'].sudo().get_param(
            'wgs_subscriptions_pos.authorization_pin_rotation_days',
            default='30',
        )
        try:
            days = int(raw_value or 0)
        except (TypeError, ValueError):
            days = 30
        return max(days, 0)

    @api.model
    def _wgs_generate_authorization_pin(self, employee=False, length=6):
        Credential = self.env['wgs.pos.authorization.credential'].sudo()
        digits = '0123456789'
        employee = employee or self.env['hr.employee']
        current_pin = str(employee.wgs_authorization_pin or '') if employee else ''
        pos_pin = str(employee.pin or '') if employee and 'pin' in employee._fields else ''
        for _attempt in range(100):
            candidate = ''.join(secrets.choice(digits) for _idx in range(length))
            if candidate in (current_pin, pos_pin):
                continue
            if not Credential.search_count([('authorization_pin', '=', candidate)]):
                return candidate
        raise ValueError(_('No se pudo generar un PIN de autorización único.'))

    def _wgs_authorization_pin_email_to(self):
        self.ensure_one()
        return self.work_email or (self.user_id.email if self.user_id else False)

    def _wgs_send_authorization_pin_email(self, pin):
        self.ensure_one()
        email_to = self._wgs_authorization_pin_email_to()
        if not email_to:
            _logger.warning('WGS authorization PIN rotation skipped email: employee_id=%s has no email', self.id)
            return False

        company = self.company_id or self.env.company
        email_from = company.email or self.env.user.email_formatted or self.env.user.email or 'no-reply@example.invalid'
        body = _(
            '<p>Hola %(employee)s,</p>'
            '<p>Tu nuevo PIN de autorización para descuentos y paquetes en POS es:</p>'
            '<p style="font-size: 20px; font-weight: 700; letter-spacing: 2px;">%(pin)s</p>'
            '<p>Este PIN es independiente de tu PIN de acceso al Punto de Venta.</p>'
        ) % {
            'employee': html_escape(self.name or ''),
            'pin': pin,
        }
        self.env['mail.mail'].sudo().create({
            'subject': _('Nuevo PIN de autorización POS'),
            'body_html': body,
            'email_to': email_to,
            'email_from': email_from,
            'auto_delete': True,
        }).send()
        return True

    def _wgs_rotate_authorization_pin(self):
        self.ensure_one()
        new_pin = self._wgs_generate_authorization_pin(self)
        self._wgs_set_authorization_pin(new_pin, fields.Datetime.now())
        self._wgs_send_authorization_pin_email(new_pin)
        return new_pin

    @api.model
    def _cron_rotate_wgs_authorization_pins(self):
        days = self._wgs_authorization_pin_rotation_days()
        if not days:
            return {'rotated': 0, 'skipped': 0}

        cutoff = fields.Datetime.now() - timedelta(days=days)
        credentials = self.env['wgs.pos.authorization.credential'].sudo().search([
            '|',
            ('last_rotated_at', '=', False),
            ('last_rotated_at', '<=', fields.Datetime.to_string(cutoff)),
        ])
        rotated = 0
        skipped = 0
        for credential in credentials:
            employee = credential.employee_id.with_context(active_test=False)
            if not employee:
                skipped += 1
                continue
            if not employee._wgs_authorization_pin_email_to():
                skipped += 1
                _logger.warning('WGS authorization PIN rotation skipped: employee_id=%s has no email', employee.id)
                continue
            try:
                employee._wgs_rotate_authorization_pin()
                rotated += 1
            except Exception:
                skipped += 1
                _logger.exception('WGS authorization PIN rotation failed for employee_id=%s', employee.id)
        return {'rotated': rotated, 'skipped': skipped}
