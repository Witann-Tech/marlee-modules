from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    wgs_authorization_pin2 = fields.Char(
        string='PIN2 autorizaciones WGS',
        copy=False,
        help='PIN usado para autorizar descuentos y acciones sensibles desde Suscripciones POS.',
    )

    @api.constrains('wgs_authorization_pin2')
    def _check_wgs_authorization_pin2(self):
        Employee = self.sudo().with_context(active_test=False)
        for employee in self:
            pin = str(employee.wgs_authorization_pin2 or '').strip()
            if not pin:
                continue
            if len(pin) < 4:
                raise ValidationError(_('El PIN2 de autorizaciones debe tener al menos 4 caracteres.'))
            duplicate = Employee.search(
                [
                    ('id', '!=', employee.id),
                    ('wgs_authorization_pin2', '=', pin),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    _('El PIN2 de autorizaciones ya está asignado a %(employee)s.') % {
                        'employee': duplicate.display_name,
                    }
                )
