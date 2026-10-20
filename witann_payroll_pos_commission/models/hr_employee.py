import math

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    witann_pos_commission_eligible = fields.Boolean(
        string='Usuario con acceso a POS', compute='_compute_witann_pos_commission_eligible',
        groups='hr_payroll.group_hr_payroll_user',
    )
    witann_pos_commission_rate = fields.Float(
        string='Comisión mensual POS (%)', default=0, digits=(7, 4), tracking=True,
        groups='hr_payroll.group_hr_payroll_user',
        help='Porcentaje mensual sobre ventas sin impuestos del usuario POS vinculado. '
             'Se paga la mitad en cada quincena del mes siguiente. 1 = 1%; 0 = sin comisión.',
    )

    @api.depends('user_id', 'user_id.active', 'user_id.all_group_ids',
                 'user_id.company_ids', 'company_id')
    def _compute_witann_pos_commission_eligible(self):
        group = self.env.ref('point_of_sale.group_pos_user')
        for employee in self:
            # Payroll officers need only this boolean, not user administration rights.
            user = employee.user_id.sudo()
            employee.witann_pos_commission_eligible = bool(
                user and user.active and not user.share
                and group in user.all_group_ids and employee.company_id in user.company_ids
            )

    @api.constrains('witann_pos_commission_rate', 'user_id', 'company_id')
    def _check_witann_pos_commission_rate(self):
        for employee in self.sudo():
            rate = employee.witann_pos_commission_rate
            if not math.isfinite(rate) or not 0 <= rate <= 100:
                raise ValidationError(_('El porcentaje mensual debe estar entre 0 y 100.'))
            if rate and not employee.witann_pos_commission_eligible:
                raise ValidationError(_('Solo puede configurar comisiones para empleados con un usuario activo con acceso a POS en su compañía.'))
