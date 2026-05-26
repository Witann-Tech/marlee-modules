import logging
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    wgs_authorization_pin = fields.Char(
        string='PIN autorización WGS',
        copy=False,
        groups='hr.group_hr_manager',
        help='PIN independiente del PIN nativo del POS. Se usa para autorizar descuentos y paquetes desde Suscripciones POS.',
    )
    wgs_authorization_pin_last_rotated_at = fields.Datetime(
        string='Última rotación PIN autorización WGS',
        copy=False,
        readonly=True,
        groups='hr.group_hr_manager',
    )

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for vals in vals_list:
            if vals.get('wgs_authorization_pin') and not vals.get('wgs_authorization_pin_last_rotated_at'):
                vals['wgs_authorization_pin_last_rotated_at'] = now
        return super().create(vals_list)

    def write(self, vals):
        values = dict(vals or {})
        if 'wgs_authorization_pin' in values and not self.env.context.get('wgs_authorization_pin_rotation'):
            values['wgs_authorization_pin_last_rotated_at'] = fields.Datetime.now() if values.get('wgs_authorization_pin') else False
        return super().write(values)

    @api.constrains('pin', 'wgs_authorization_pin')
    def _check_wgs_authorization_pin(self):
        Employee = self.sudo().with_context(active_test=False)
        for employee in self:
            authorization_pin = str(employee.wgs_authorization_pin or '').strip()
            if not authorization_pin:
                continue
            pos_pin = str(employee.pin or '').strip() if 'pin' in employee._fields else ''
            if pos_pin and authorization_pin == pos_pin:
                raise ValidationError(_('El PIN de autorización WGS debe ser diferente al PIN de acceso POS.'))
            duplicate = Employee.search([
                ('id', '!=', employee.id),
                ('wgs_authorization_pin', '=', authorization_pin),
            ], limit=1)
            if duplicate:
                raise ValidationError(_('El PIN de autorización WGS ya está asignado a otro empleado.'))

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
        Employee = self.sudo().with_context(active_test=False)
        digits = '0123456789'
        employee = employee or self.env['hr.employee']
        current_pin = str(employee.wgs_authorization_pin or '') if employee else ''
        pos_pin = str(employee.pin or '') if employee and 'pin' in employee._fields else ''
        for _attempt in range(100):
            candidate = ''.join(secrets.choice(digits) for _idx in range(length))
            if candidate in (current_pin, pos_pin):
                continue
            if not Employee.search_count([('wgs_authorization_pin', '=', candidate)]):
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
        self.with_context(wgs_authorization_pin_rotation=True).sudo().write({
            'wgs_authorization_pin': new_pin,
            'wgs_authorization_pin_last_rotated_at': fields.Datetime.now(),
        })
        self._wgs_send_authorization_pin_email(new_pin)
        return new_pin

    @api.model
    def _cron_rotate_wgs_authorization_pins(self):
        days = self._wgs_authorization_pin_rotation_days()
        if not days:
            return {'rotated': 0, 'skipped': 0}

        now = fields.Datetime.now()
        cutoff = now - timedelta(days=days)
        employees = self.sudo().with_context(active_test=False).search([
            ('wgs_authorization_pin', '!=', False),
            '|',
            ('wgs_authorization_pin_last_rotated_at', '=', False),
            ('wgs_authorization_pin_last_rotated_at', '<=', fields.Datetime.to_string(cutoff)),
        ])
        rotated = 0
        skipped = 0
        for employee in employees:
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
