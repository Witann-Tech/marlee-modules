import math

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    witann_pos_source_config_id = fields.Many2one(
        'pos.config', string='POS de origen', check_company=False, copy=False, ondelete='restrict',
        groups='hr_payroll.group_hr_payroll_user', tracking=True,
        help='Opcional: POS cuyas ventas se pagarán en esta nómina, incluso si pertenece a otra compañía.',
    )
    witann_pos_source_employee_id = fields.Many2one(
        'hr.employee', string='Cajera o cajero de origen', check_company=False, copy=False, ondelete='restrict',
        groups='hr_payroll.group_hr_payroll_user', tracking=True,
    )
    witann_pos_source_company_id = fields.Many2one(
        related='witann_pos_source_config_id.company_id',
        groups='hr_payroll.group_hr_payroll_user',
    )

    @api.onchange('witann_pos_source_config_id')
    def _onchange_witann_pos_source_config(self):
        self.witann_pos_source_employee_id = False

    def _witann_pos_source_is_eligible(self):
        self.ensure_one()
        config = self.witann_pos_source_config_id.sudo()
        cashier = self.witann_pos_source_employee_id.sudo()
        return bool(config and cashier and config.active and config.module_pos_hr
                    and cashier.active and cashier.company_id == config.company_id
                    and cashier.filtered_domain(config._employee_domain(-1)))

    def _witann_check_source_configuration_access(self):
        if not self:
            return
        if not self.env.su and not self.env.user.has_group('hr_payroll.group_hr_payroll_manager'):
            raise AccessError(_('Solo un responsable de Nómina puede configurar el origen POS.'))
        # Configure using the caller's normal access to both companies. Subsequent
        # payroll calculations may read only this saved source without POS rights.
        for employee in self:
            employee.witann_pos_source_config_id.check_access('read')
            employee.witann_pos_source_employee_id.check_access('read')

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        for employee, vals in zip(employees, vals_list):
            if {'witann_pos_source_config_id', 'witann_pos_source_employee_id'} & vals.keys():
                employee._witann_check_source_configuration_access()
        return employees

    def write(self, vals):
        result = super().write(vals)
        if {'witann_pos_source_config_id', 'witann_pos_source_employee_id'} & vals.keys():
            self._witann_check_source_configuration_access()
        elif 'company_id' in vals:
            self.filtered('witann_pos_source_config_id')._witann_check_source_configuration_access()
        return result

    @api.constrains('witann_pos_source_config_id', 'witann_pos_source_employee_id', 'company_id')
    def _check_witann_pos_source(self):
        for employee in self.sudo():
            if bool(employee.witann_pos_source_config_id) != bool(employee.witann_pos_source_employee_id):
                raise ValidationError(_('Seleccione tanto el POS como la cajera o cajero de origen.'))
            if employee.witann_pos_source_config_id and not employee._witann_pos_source_is_eligible():
                raise ValidationError(_('La cajera o cajero debe tener acceso al POS de origen activo y pertenecer a su compañía.'))
            if (employee.witann_pos_source_config_id and
                    employee.witann_pos_source_company_id.currency_id != employee.company_id.currency_id):
                raise ValidationError(_('La compañía del POS y la de nómina deben utilizar la misma moneda.'))

    witann_pos_commission_eligible = fields.Boolean(
        string='Empleado con acceso a POS', compute='_compute_witann_pos_commission_eligible',
        groups='hr_payroll.group_hr_payroll_user',
    )
    witann_pos_commission_rate = fields.Float(
        string='Comisión mensual POS (%)', default=0, digits=(7, 4), tracking=True,
        groups='hr_payroll.group_hr_payroll_user',
        help='Porcentaje mensual sobre ventas sin impuestos del cajero o usuario POS vinculado. '
             'Se paga la mitad en cada quincena del mes siguiente. 1 = 1%; 0 = sin comisión.',
    )

    @api.depends('active', 'user_id', 'user_id.active', 'user_id.share', 'user_id.all_group_ids',
                 'user_id.company_ids', 'company_id', 'witann_pos_source_config_id',
                 'witann_pos_source_employee_id', 'witann_pos_source_employee_id.active',
                 'witann_pos_source_employee_id.company_id')
    def _compute_witann_pos_commission_eligible(self):
        group = self.env.ref('point_of_sale.group_pos_user')
        employees = self.sudo()
        cashier_ids = set()
        configs = self.env['pos.config'].sudo().search([
            ('company_id', 'in', employees.company_id.ids),
            ('active', '=', True),
            ('module_pos_hr', '=', True),
        ])
        for config in configs:
            # Reuse native cashier access, including the "all employees" mode.
            # -1 avoids treating every employee without a user as the session user.
            candidates = employees.filtered(lambda e: e.company_id == config.company_id)
            cashier_ids.update(candidates.filtered_domain(config._employee_domain(-1)).ids)
        for employee in self:
            if employee.witann_pos_source_config_id:
                employee.witann_pos_commission_eligible = employee.active and employee._witann_pos_source_is_eligible()
                continue
            # Payroll officers need only this boolean, not user administration rights.
            user = employee.user_id.sudo()
            employee.witann_pos_commission_eligible = bool(
                employee.active and (
                    employee.id in cashier_ids
                    or (user and user.active and not user.share
                        and group in user.all_group_ids and employee.company_id in user.company_ids)
                )
            )

    @api.constrains('witann_pos_commission_rate', 'user_id', 'company_id',
                    'witann_pos_source_config_id', 'witann_pos_source_employee_id')
    def _check_witann_pos_commission_rate(self):
        for employee in self.sudo():
            rate = employee.witann_pos_commission_rate
            if not math.isfinite(rate) or not 0 <= rate <= 100:
                raise ValidationError(_('El porcentaje mensual debe estar entre 0 y 100.'))
            if rate and not employee.witann_pos_commission_eligible:
                raise ValidationError(_('Configure acceso POS propio o un POS y cajera o cajero de origen válidos antes de asignar una comisión.'))
