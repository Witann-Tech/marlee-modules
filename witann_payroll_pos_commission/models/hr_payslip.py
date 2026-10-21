from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import html_escape

from ..calculation import commission_amount, commission_period


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    witann_pos_period = fields.Date(string='Quincena comisionada', readonly=True, copy=False)
    witann_pos_month = fields.Date(string='Mes de ventas', readonly=True, copy=False)
    witann_pos_user_id = fields.Many2one('res.users', string='Usuario POS', readonly=True, copy=False)
    witann_pos_source_config_id = fields.Many2one('pos.config', string='POS de origen', readonly=True, copy=False, check_company=False, ondelete='restrict')
    witann_pos_source_employee_id = fields.Many2one('hr.employee', string='Cajera o cajero de origen', readonly=True, copy=False, check_company=False, ondelete='restrict')
    witann_pos_rate = fields.Float(string='Porcentaje mensual (%)', digits=(7, 4), readonly=True, copy=False)
    witann_pos_base = fields.Monetary(string='Ventas sin impuestos', readonly=True, copy=False)
    witann_pos_amount = fields.Monetary(string='Comisión por venta', readonly=True, copy=False)
    witann_pos_timezone = fields.Char(string='Zona horaria del corte', readonly=True, copy=False)
    witann_pos_order_count = fields.Integer(string='Tickets considerados', readonly=True, copy=False)
    witann_pos_evidence = fields.Json(string='Detalle del cálculo', readonly=True, copy=False,
                                    groups='hr_payroll.group_hr_payroll_user')
    witann_pos_detail = fields.Html(
        string='Detalle de tickets', compute='_compute_witann_pos_detail',
        groups='hr_payroll.group_hr_payroll_user',
    )

    _witann_pos_period_unique = models.UniqueIndex(
        '(company_id, employee_id, witann_pos_period) '
        "WHERE witann_pos_period IS NOT NULL AND state != 'cancel' AND credit_note IS NOT TRUE",
        'Ya existe una comisión POS para este empleado y quincena. Cancele el recibo anterior antes de sustituirlo.',
    )

    @api.depends('witann_pos_evidence', 'currency_id')
    def _compute_witann_pos_detail(self):
        for slip in self:
            rows = []
            for item in slip.witann_pos_evidence or []:
                rows.append('<tr>%s</tr>' % ''.join('<td>%s</td>' % html_escape(str(value)) for value in (
                    item['name'], item['date_order_utc'], item['currency'],
                    f"{item['untaxed']:,.2f}", f"{item['company_amount']:,.2f}",
                )))
            slip.witann_pos_detail = (
                '<table class="table table-sm"><thead><tr><th>Ticket</th><th>Fecha UTC</th>'
                '<th>Moneda</th><th>Venta sin impuestos</th><th>Base en moneda de nómina</th>'
                '</tr></thead><tbody>%s</tbody></table>' % ''.join(rows)
            ) if rows else False

    def _witann_pos_enabled(self):
        self.ensure_one()
        return bool(
            not self.credit_note and self.country_code == 'MX'
            and self.struct_id == self.env.ref('l10n_mx_hr_payroll.l10n_mx_regular_pay')
            and self.employee_id.witann_pos_commission_eligible
            and self.employee_id.witann_pos_commission_rate > 0
        )

    def _witann_pos_snapshot(self):
        self.ensure_one()
        if self.company_id not in self.env.companies:
            raise AccessError(_('La compañía del recibo no está permitida.'))
        if self.employee_id.company_id != self.company_id:
            raise ValidationError(_('El empleado y el recibo deben pertenecer a la misma compañía.'))
        schedule = self.version_id.schedule_pay or self.version_id.structure_type_id.default_schedule_pay
        # Mexican localization uses bi-weekly for calendar fortnights, not 14_days.
        if schedule != 'bi-weekly':
            raise UserError(_('La comisión POS requiere la frecuencia quincenal de la nómina mexicana.'))
        timezone = self.company_id.resource_calendar_id.tz or 'America/Mexico_City'
        try:
            period, month, start, stop = commission_period(self.date_from, self.date_to, timezone)
        except ValueError as exc:
            raise UserError(str(exc)) from exc

        # A validated payment locks the monthly basis for the other fortnight.
        previous = self.search([
            ('id', '!=', self.id), ('company_id', '=', self.company_id.id),
            ('employee_id', '=', self.employee_id.id), ('witann_pos_month', '=', month),
            ('state', 'in', ['validated', 'paid']), ('credit_note', '=', False),
        ], order='id', limit=1)
        if previous:
            base = previous.witann_pos_base
            rate = previous.witann_pos_rate
            user = previous.witann_pos_user_id
            source_config = previous.witann_pos_source_config_id
            source_employee = previous.witann_pos_source_employee_id or previous.employee_id
            timezone = previous.witann_pos_timezone
            evidence = previous.witann_pos_evidence
            count = previous.witann_pos_order_count
        else:
            source_config = self.employee_id.witann_pos_source_config_id.sudo()
            source_employee = (self.employee_id.witann_pos_source_employee_id or self.employee_id).sudo()
            source_company = source_config.company_id if source_config else self.company_id
            if source_company.currency_id != self.currency_id:
                raise UserError(_('La compañía del POS y la de nómina deben utilizar la misma moneda.'))
            user = source_employee.user_id
            rate = self.employee_id.witann_pos_commission_rate
            # A named cashier owns the sale, even when another user opened POS.
            # Legacy orders without a cashier may fall back to a linked user.
            seller_domain = Domain('employee_id', '=', source_employee.id)
            if source_config:
                seller_domain &= Domain('config_id', '=', source_config.id)
            elif user:
                seller_domain |= Domain.AND([
                    Domain('employee_id', '=', False), Domain('user_id', '=', user.id),
                ])
            # Payroll does not need access to the POS application. The elevated read
            # is strictly scoped to this authorized company, seller and closed month.
            orders = self.env['pos.order'].sudo().search(seller_domain & Domain([
                ('company_id', '=', source_company.id),
                ('state', 'in', ['paid', 'done', 'invoiced']),
                ('date_order', '>=', start), ('date_order', '<', stop),
            ]), order='date_order, id')
            evidence = []
            base = 0.0
            for order in orders:
                # Order totals already carry the refund sign, discounts and rounded
                # taxes. Using line subtotals would invert refunds on newer POS builds.
                untaxed = order.amount_total - order.amount_tax
                if order.currency_id == self.currency_id:
                    amount = untaxed
                else:
                    if order.currency_rate <= 0:
                        raise UserError(_('El ticket %s no tiene un tipo de cambio válido.') % order.display_name)
                    amount = untaxed / order.currency_rate
                base += amount
                evidence.append({
                    'order_id': order.id, 'name': order.name,
                    'employee_id': order.employee_id.id, 'user_id': order.user_id.id,
                    'config_id': order.config_id.id, 'config_name': order.config_id.display_name,
                    'company_id': order.company_id.id, 'company_name': order.company_id.display_name,
                    'date_order_utc': fields.Datetime.to_string(order.date_order),
                    'untaxed': untaxed, 'currency': order.currency_id.name,
                    'currency_rate': order.currency_rate, 'company_amount': amount,
                })
            base = self.currency_id.round(base)
            count = len(orders)

        amount = commission_amount(base, rate, period.day == 16, self.currency_id.rounding)
        return {
            'witann_pos_period': period if amount else False,
            'witann_pos_month': month, 'witann_pos_user_id': user.id,
            'witann_pos_source_config_id': source_config.id,
            'witann_pos_source_employee_id': source_employee.id,
            'witann_pos_rate': rate, 'witann_pos_base': base, 'witann_pos_amount': amount,
            'witann_pos_timezone': timezone, 'witann_pos_order_count': count,
            'witann_pos_evidence': evidence,
        }

    def _witann_prepare_pos_commission(self):
        self.check_access('write')
        if not self.env.user.has_group('hr_payroll.group_hr_payroll_user'):
            raise AccessError(_('Se requieren permisos de Nómina para calcular comisiones.'))
        # Onchange pseudo-records must not create database inputs. The saved
        # document is recalculated by compute_sheet and before validation.
        for slip in self.filtered(lambda s: s.id and s.state == 'draft' and not s.credit_note):
            values = {
                'witann_pos_period': False, 'witann_pos_month': False,
                'witann_pos_user_id': False, 'witann_pos_rate': 0,
                'witann_pos_source_config_id': False, 'witann_pos_source_employee_id': False,
                'witann_pos_base': 0, 'witann_pos_amount': 0,
                'witann_pos_timezone': False, 'witann_pos_order_count': 0,
                'witann_pos_evidence': False,
            }
            if slip._witann_pos_enabled():
                values = slip._witann_pos_snapshot()
            amount = values['witann_pos_amount']
            if amount:
                if self.sudo().search_count([
                    ('id', '!=', slip.id), ('company_id', '=', slip.company_id.id),
                    ('employee_id', '=', slip.employee_id.id),
                    ('witann_pos_period', '=', values['witann_pos_period']),
                    ('state', '!=', 'cancel'), ('credit_note', '=', False),
                ], limit=1):
                    raise ValidationError(_('Ya existe una comisión POS para este empleado y quincena. Cancele el recibo anterior antes de sustituirlo.'))
                manual = slip.input_line_ids.filtered(lambda i: i.code == 'COMMISSIONS' and not i.witann_pos_commission)
                if manual:
                    # Native CFDI groups by salary rule and would retain only one of
                    # multiple COMMISSIONS lines. Never silently overwrite manual pay.
                    raise UserError(_('El recibo contiene comisiones manuales. Concilie esas entradas antes de calcular la comisión automática POS.'))
                rule = self.env.ref('l10n_mx_hr_payroll.l10n_mx_regular_pay_commissions')
                input_type = self.env.ref('l10n_mx_hr_payroll.l10n_mx_input_commissions')
                if (rule not in slip.struct_id.rule_ids or not rule.active
                        or rule.condition_select != 'input' or rule.amount_select != 'input'
                        or rule.condition_other_input_id != input_type or rule.amount_other_input_id != input_type
                        or rule.l10n_mx_concept != self.env.ref('l10n_mx_hr_payroll_account_edi.l10n_mx_concept_p28')):
                    raise UserError(_('Restaure la regla nativa de comisiones y su concepto CFDI antes de calcular la comisión POS.'))
            # Avoid recursive line recomputation when updating this managed input.
            with self.env.protecting([self._fields['line_ids']], slip):
                super(HrPayslip, slip).write(values)
                slip._witann_sync_pos_claims()
                self.env['hr.payslip.input']._witann_sync_pos_commission(slip, amount)

    def _witann_pos_claim_values(self):
        self.ensure_one()
        if not self.witann_pos_amount or not self.witann_pos_period or self.credit_note or self.state == 'cancel':
            return []
        employee = self.witann_pos_source_employee_id or self.employee_id
        sources = set()
        if self.witann_pos_source_config_id:
            sources.add((self.witann_pos_source_config_id.id, 'employee:%s' % employee.id))
        else:
            evidence = self.witann_pos_evidence or []
            # Earlier versions did not store the POS in evidence. Resolve only
            # those recorded tickets to protect pre-upgrade commissions as well.
            old_orders = self.env['pos.order'].sudo().browse([
                item['order_id'] for item in evidence if not item.get('config_id')
            ]).exists()
            old_configs = {order.id: order.config_id.id for order in old_orders}
            old_cashiers = {order.id: order.employee_id.id for order in old_orders}
            for item in evidence:
                config_id = item.get('config_id') or old_configs.get(item['order_id'])
                if not config_id:
                    raise UserError(_('No se puede identificar el POS de un ticket histórico comisionado. Revise el recibo antes de continuar.'))
                sources.add((config_id, 'employee:%s' % employee.id))
                cashier_id = item.get('employee_id', old_cashiers.get(item['order_id']))
                if cashier_id:
                    sources.add((config_id, 'employee:%s' % cashier_id))
                if not item.get('employee_id') and self.witann_pos_user_id:
                    sources.add((config_id, 'user:%s' % self.witann_pos_user_id.id))
        return [{'payslip_id': self.id, 'config_id': config_id, 'seller_key': key,
                 'period': self.witann_pos_period} for config_id, key in sorted(sources)]

    def _witann_sync_pos_claims(self):
        Claim = self.env['witann.pos.commission.claim'].sudo()
        for slip in self:
            values = slip._witann_pos_claim_values()
            for value in values:
                if Claim.search_count([
                    ('payslip_id', '!=', slip.id), ('config_id', '=', value['config_id']),
                    ('seller_key', '=', value['seller_key']), ('period', '=', value['period']),
                ], limit=1):
                    raise ValidationError(_('Este origen POS ya tiene una comisión en la misma quincena. Cancele el recibo anterior antes de sustituirlo.'))
            Claim.search([('payslip_id', '=', slip.id)]).unlink()
            Claim.create(values)

    def _get_payslip_lines(self):
        if self.filtered(lambda s: s.credit_note and s.origin_payslip_id.witann_pos_month):
            raise UserError(_('Conserve las líneas de reversión generadas por Odoo; no recalcule una devolución de comisión POS.'))
        self._witann_prepare_pos_commission()
        return super()._get_payslip_lines()

    def _witann_check_pos_lines(self):
        for slip in self.filtered(lambda s: s.witann_pos_amount and not s.credit_note):
            try:
                period, month, _, _ = commission_period(slip.date_from, slip.date_to, slip.witann_pos_timezone)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            if period != slip.witann_pos_period or month != slip.witann_pos_month:
                raise ValidationError(_('El periodo cambió después del cálculo POS. Recalcule el recibo.'))
            inputs = slip.input_line_ids.filtered(lambda i: i.code == 'COMMISSIONS')
            lines = slip.line_ids.filtered(lambda l: l.code == 'COMMISSIONS')
            if (len(inputs) != 1 or not inputs.witann_pos_commission or len(lines) != 1
                    or slip.currency_id.compare_amounts(inputs.amount, slip.witann_pos_amount)
                    or slip.currency_id.compare_amounts(lines.total, slip.witann_pos_amount)):
                raise ValidationError(_('La comisión del recibo no coincide con su cálculo POS. Recalcule el recibo en borrador.'))

    def action_payslip_done(self):
        self.filtered(lambda s: s.state == 'draft' and (s._witann_pos_enabled() or s.witann_pos_month)).compute_sheet()
        self._witann_check_pos_lines()
        return super().action_payslip_done()

    def _l10n_mx_edi_add_payslip_cfdi_values(self, cfdi_values=None):
        self._witann_check_pos_lines()
        values = super()._l10n_mx_edi_add_payslip_cfdi_values(cfdi_values)
        if self.witann_pos_amount:
            concept = self.env.ref('l10n_mx_hr_payroll_account_edi.l10n_mx_concept_p28')
            for perception in values.get('percepcion_list', []):
                if perception['clave'] == concept.payroll_code and perception['tipo_percepcion'] == concept.sat_code:
                    perception['concepto'] = 'Comisión por venta'
        return values

    @api.model_create_multi
    def create(self, vals_list):
        if any(any(key.startswith('witann_pos_') for key in values) for values in vals_list):
            raise ValidationError(_('El detalle de comisión POS se genera al calcular el recibo.'))
        return super().create(vals_list)

    def write(self, vals):
        if any(key.startswith('witann_pos_') for key in vals):
            raise ValidationError(_('El detalle de comisión POS se genera al calcular el recibo.'))
        protected = {'employee_id', 'version_id', 'company_id', 'struct_id', 'date_from', 'date_to',
                     'input_line_ids', 'line_ids', 'credit_note'}
        if protected.intersection(vals) and self.filtered(lambda s: s.witann_pos_month and s.state in ('validated', 'paid')):
            raise ValidationError(_('Regrese el recibo a borrador mediante el flujo nativo antes de modificar su comisión POS.'))
        if vals.get('state') in ('draft', 'cancel') and self.filtered(lambda s: s.witann_pos_month and s.l10n_mx_edi_cfdi_state == 'sent'):
            raise ValidationError(_('Cancele primero el CFDI mediante el flujo nativo antes de recalcular la comisión.'))
        if vals.get('state') in ('validated', 'paid'):
            for slip in self:
                if slip._witann_pos_enabled() and not slip.witann_pos_month:
                    raise ValidationError(_('Calcule el recibo antes de validar la comisión POS.'))
            self._witann_check_pos_lines()
        result = super().write(vals)
        if 'state' in vals:
            self._witann_sync_pos_claims()
        return result
