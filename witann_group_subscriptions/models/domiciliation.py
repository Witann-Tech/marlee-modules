"""Authoritative contracts and monthly installments for WGS domiciliation."""

from calendar import monthrange
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WgsSubscriptionDomiciliationContract(models.Model):
    _name = 'wgs.subscription.domiciliation.contract'
    _description = 'Contrato domiciliado WGS'
    _order = 'term_start_date desc, id desc'

    _subscription_uniq = models.Constraint(
        'unique(subscription_id)',
        'Una suscripción solo puede tener un contrato domiciliado WGS.',
    )

    subscription_id = fields.Many2one(
        'sale.order', required=True, ondelete='cascade', index=True, string='Suscripción'
    )
    company_id = fields.Many2one(related='subscription_id.company_id', store=True, index=True)
    partner_id = fields.Many2one(related='subscription_id.partner_id', store=True, index=True)
    product_id = fields.Many2one('product.product', required=True, ondelete='restrict', string='Paquete')
    plan_id = fields.Many2one('sale.subscription.plan', required=True, ondelete='restrict', string='Plan recurrente')
    currency_id = fields.Many2one(related='subscription_id.currency_id', store=True)
    monthly_amount = fields.Monetary(required=True, currency_field='currency_id', string='Mensualidad')
    access_start_date = fields.Date(required=True, index=True, string='Inicio de acceso')
    term_start_date = fields.Date(required=True, index=True, string='Inicio de plazo')
    term_end_date = fields.Date(required=True, index=True, string='Fin de plazo')
    term_months = fields.Integer(required=True, string='Mensualidades')
    state = fields.Selection(
        [('active', 'Activo'), ('cancelled', 'Cancelado'), ('completed', 'Concluido')],
        default='active', required=True, index=True,
    )
    installment_ids = fields.One2many(
        'wgs.subscription.domiciliation.installment', 'contract_id', string='Mensualidades'
    )
    paid_through_date = fields.Date(compute='_compute_payment_summary', string='Pagado hasta')
    overdue_installment_count = fields.Integer(compute='_compute_payment_summary', string='Mensualidades exigibles pendientes')
    is_access_current = fields.Boolean(compute='_compute_payment_summary', string='Acceso al corriente')

    @api.constrains('plan_id', 'term_months', 'term_start_date', 'term_end_date', 'access_start_date')
    def _check_contract_dates(self):
        for contract in self:
            if not contract.plan_id.wgs_domiciliation_enabled:
                raise ValidationError(_('El plan recurrente del contrato debe estar marcado como domiciliado WGS.'))
            if contract.term_months < 2:
                raise ValidationError(_('El plazo forzoso domiciliado debe contener al menos dos meses.'))
            if contract.term_start_date > contract.term_end_date:
                raise ValidationError(_('La fecha final del plazo no puede ser anterior al inicio.'))
            if contract.access_start_date < contract.term_start_date or contract.access_start_date > contract.term_end_date:
                raise ValidationError(_('El inicio de acceso debe quedar dentro del plazo forzoso.'))

    @api.depends('installment_ids.state', 'installment_ids.period_end_date', 'state', 'access_start_date', 'term_end_date')
    def _compute_payment_summary(self):
        today = self.env['sale.order']._wgs_get_subscription_business_today()
        for contract in self:
            due_installments = contract._get_required_installments(today=today)
            unpaid = due_installments.filtered(lambda installment: installment.state != 'paid')
            paid = contract.installment_ids.filtered(lambda installment: installment.state == 'paid').sorted(
                key=lambda installment: (installment.period_end_date, installment.sequence)
            )
            contract.paid_through_date = paid[-1:].period_end_date if paid else False
            contract.overdue_installment_count = len(unpaid)
            contract.is_access_current = bool(
                contract.state == 'active'
                and contract.access_start_date <= today <= contract.term_end_date
                and not unpaid
            )

    @api.model
    def _wgs_month_bounds(self, anchor):
        anchor = fields.Date.to_date(anchor)
        return anchor.replace(day=1), anchor.replace(day=monthrange(anchor.year, anchor.month)[1])

    @api.model
    def _wgs_prorated_amount(self, monthly_amount, access_start_date, month_end_date):
        days_in_month = int(month_end_date.day or 0)
        charge_days = (month_end_date - access_start_date).days + 1
        return round(max(float(monthly_amount or 0.0), 0.0) * charge_days / days_in_month, 2)

    @api.model
    def wgs_build_initial_schedule(self, *, start_date, monthly_amount, term_months):
        """Build the immutable calendar schedule before a contract is persisted."""
        access_start = fields.Date.to_date(start_date)
        if not access_start:
            raise ValidationError(_('La contratación domiciliada requiere una fecha de inicio.'))
        term_months = int(term_months or 0)
        if term_months < 2:
            raise ValidationError(_('El plazo domiciliado debe tener al menos dos mensualidades.'))
        monthly_amount = round(max(float(monthly_amount or 0.0), 0.0), 2)
        if not monthly_amount:
            raise ValidationError(_('La mensualidad domiciliada debe ser mayor a cero.'))

        term_start, first_month_end = self._wgs_month_bounds(access_start)
        installments = []
        for sequence in range(1, term_months + 1):
            period_start = term_start + relativedelta(months=sequence - 1)
            period_start, period_end = self._wgs_month_bounds(period_start)
            kind = 'regular'
            amount = monthly_amount
            if sequence == 1:
                kind = 'initial_proration'
                amount = self._wgs_prorated_amount(monthly_amount, access_start, first_month_end)
            elif sequence == term_months:
                kind = 'terminal_prepayment'
            installments.append({
                'sequence': sequence,
                'kind': kind,
                'period_start_date': period_start,
                'period_end_date': period_end,
                'due_date': access_start if sequence == 1 else period_start,
                'amount': amount,
            })
        return {
            'access_start_date': access_start,
            'term_start_date': term_start,
            'term_end_date': installments[-1]['period_end_date'],
            'term_months': term_months,
            'installments': installments,
            'initial_installment_sequences': [1, term_months],
            'initial_charge': round(installments[0]['amount'] + installments[-1]['amount'], 2),
        }

    @api.model
    def wgs_create_for_subscription(self, subscription, *, product, plan, start_date, monthly_amount, pos_line=False, restart=False):
        """Create the contract only after the POS sale has become paid and synchronized."""
        subscription.ensure_one()
        existing = self.search([('subscription_id', '=', subscription.id)], limit=1)
        if existing:
            if not restart and existing.state == 'active' and existing.term_end_date >= fields.Date.to_date(start_date):
                return existing
            existing.installment_ids.unlink()
        if not plan.wgs_domiciliation_enabled:
            return self.browse()

        schedule = self.wgs_build_initial_schedule(
            start_date=start_date,
            monthly_amount=monthly_amount,
            term_months=plan.wgs_domiciliation_term_months,
        )
        contract_values = {
            'subscription_id': subscription.id,
            'product_id': product.id,
            'plan_id': plan.id,
            'monthly_amount': monthly_amount,
            'access_start_date': schedule['access_start_date'],
            'term_start_date': schedule['term_start_date'],
            'term_end_date': schedule['term_end_date'],
            'term_months': schedule['term_months'],
            'state': 'active',
            'installment_ids': [
                fields.Command.create({**installment, 'state': 'due'})
                for installment in schedule['installments']
            ],
        }
        contract = existing or self.create(contract_values)
        if existing:
            existing.write(contract_values)
        subscription.write({'wgs_domiciliation_contract_id': contract.id})
        if pos_line:
            contract.wgs_apply_pos_payment(
                pos_line,
                installment_sequences=schedule['initial_installment_sequences'],
                allow_terminal_prepayment=True,
            )
        return contract

    def _get_required_installments(self, today=False):
        self.ensure_one()
        today = fields.Date.to_date(today) or self.env['sale.order']._wgs_get_subscription_business_today(
            company=self.company_id
        )
        return self.installment_ids.filtered(lambda installment: installment.period_start_date <= today)

    def wgs_get_due_installments(self, today=False):
        self.ensure_one()
        return self._get_required_installments(today=today).filtered(lambda installment: installment.state != 'paid').sorted(
            key=lambda installment: installment.sequence
        )

    def wgs_get_renewal_quote(self, months_to_pay=False, today=False):
        self.ensure_one()
        due_installments = self.wgs_get_due_installments(today=today)
        if months_to_pay:
            months_to_pay = max(1, min(int(months_to_pay), len(due_installments)))
            selected = due_installments[:months_to_pay]
        else:
            selected = due_installments
        return {
            'contract_id': self.id,
            'due_installment_count': len(due_installments),
            'selected_installment_sequences': selected.mapped('sequence'),
            'amount_due_total': round(sum(selected.mapped('amount')), 2),
            'access_restored': bool(
                selected and len(selected) == len(due_installments)
                and self.access_start_date <= (fields.Date.to_date(today) or self.env['sale.order']._wgs_get_subscription_business_today()) <= self.term_end_date
            ),
            'installments': [installment.wgs_as_payload() for installment in due_installments],
        }

    def wgs_apply_pos_payment(self, pos_line, *, installment_sequences, allow_terminal_prepayment=False):
        """Mark exactly the quoted full monthly installments paid, once per POS line."""
        self.ensure_one()
        pos_line.ensure_one()
        sequences = sorted({int(sequence) for sequence in (installment_sequences or []) if int(sequence) > 0})
        if not sequences:
            raise ValidationError(_('Selecciona al menos una mensualidad domiciliada para cobrar.'))
        installments = self.installment_ids.filtered(lambda installment: installment.sequence in sequences).sorted(
            key=lambda installment: installment.sequence
        )
        if len(installments) != len(sequences):
            raise ValidationError(_('La selección de mensualidades no pertenece al contrato domiciliado.'))
        due_sequences = set(self.wgs_get_due_installments().mapped('sequence'))
        allowed_sequences = due_sequences
        if allow_terminal_prepayment:
            terminal = self.installment_ids.filtered(lambda installment: installment.kind == 'terminal_prepayment')
            allowed_sequences |= set(terminal.mapped('sequence'))
        if not set(sequences).issubset(allowed_sequences):
            raise ValidationError(_('Solo se pueden cobrar mensualidades vencidas o exigibles del contrato domiciliado.'))
        already_paid = installments.filtered(lambda installment: installment.state == 'paid')
        if already_paid:
            if all(installment.paid_pos_line_id == pos_line for installment in installments):
                return installments
            raise ValidationError(_('Una mensualidad domiciliada ya fue aplicada a otro pago.'))

        expected_amount = round(sum(installments.mapped('amount')), 2)
        discount = max(min(float(getattr(pos_line, 'discount', 0.0) or 0.0), 100.0), 0.0)
        paid_amount = round(
            abs(float(pos_line.qty or 0.0) * float(pos_line.price_unit or 0.0)) * (1 - discount / 100.0),
            2,
        )
        if abs(expected_amount - paid_amount) > 0.01:
            raise ValidationError(_(
                'El importe del ticket (%(ticket).2f) no coincide con la cartera domiciliada (%(expected).2f).'
            ) % {'ticket': paid_amount, 'expected': expected_amount})
        paid_at = fields.Datetime.now()
        installments.write({
            'state': 'paid',
            'paid_pos_order_id': pos_line.order_id.id,
            'paid_pos_line_id': pos_line.id,
            'paid_at': paid_at,
        })
        return installments

    def wgs_import_paid_installments(self, installment_sequences):
        self.ensure_one()
        sequences = sorted({int(sequence) for sequence in (installment_sequences or []) if int(sequence) > 0})
        installments = self.installment_ids.filtered(lambda installment: installment.sequence in sequences)
        if len(installments) != len(sequences):
            raise ValidationError(_('La importación contiene mensualidades fuera del plazo domiciliado.'))
        installments.write({'state': 'paid', 'payment_source': 'import', 'paid_at': fields.Datetime.now()})
        return installments


class WgsSubscriptionDomiciliationInstallment(models.Model):
    _name = 'wgs.subscription.domiciliation.installment'
    _description = 'Mensualidad domiciliada WGS'
    _order = 'contract_id, sequence'

    _contract_sequence_uniq = models.Constraint(
        'unique(contract_id, sequence)', 'No puede existir más de una mensualidad por periodo del contrato.'
    )

    contract_id = fields.Many2one(
        'wgs.subscription.domiciliation.contract', required=True, ondelete='cascade', index=True
    )
    subscription_id = fields.Many2one(related='contract_id.subscription_id', store=True, index=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)
    sequence = fields.Integer(required=True, index=True, string='Mes de contrato')
    kind = fields.Selection(
        [('initial_proration', 'Proporcional inicial'), ('regular', 'Mensualidad'), ('terminal_prepayment', 'Último mes anticipado')],
        required=True,
    )
    period_start_date = fields.Date(required=True, index=True)
    period_end_date = fields.Date(required=True, index=True)
    due_date = fields.Date(required=True, index=True)
    amount = fields.Monetary(required=True, currency_field='currency_id')
    state = fields.Selection([('due', 'Pendiente'), ('paid', 'Pagada')], default='due', required=True, index=True)
    payment_source = fields.Selection([('pos', 'POS'), ('import', 'Importación')], default='pos', required=True)
    paid_pos_order_id = fields.Many2one('pos.order', ondelete='restrict', copy=False)
    paid_pos_line_id = fields.Many2one('pos.order.line', ondelete='restrict', copy=False)
    paid_at = fields.Datetime(copy=False)

    @api.constrains('sequence', 'period_start_date', 'period_end_date', 'amount')
    def _check_installment_values(self):
        for installment in self:
            if installment.sequence < 1:
                raise ValidationError(_('El número de mensualidad debe ser positivo.'))
            if installment.period_end_date < installment.period_start_date:
                raise ValidationError(_('La fecha final de mensualidad no puede ser anterior al inicio.'))
            if installment.amount < 0:
                raise ValidationError(_('El importe de una mensualidad no puede ser negativo.'))

    def wgs_as_payload(self):
        self.ensure_one()
        return {
            'sequence': self.sequence,
            'kind': self.kind,
            'period_start_date': fields.Date.to_string(self.period_start_date),
            'period_end_date': fields.Date.to_string(self.period_end_date),
            'due_date': fields.Date.to_string(self.due_date),
            'amount': float(self.amount),
            'state': self.state,
        }
