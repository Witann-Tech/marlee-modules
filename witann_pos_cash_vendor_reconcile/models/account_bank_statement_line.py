import math

from odoo import _, api, Command, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL, clean_context


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    witann_vendor_bill_ids = fields.Many2many(
        'account.move', compute='_compute_witann_vendor_reconciliation',
        store=True, string='Facturas conciliadas')
    witann_vendor_reconciliation_state = fields.Selection([
        ('pending', 'Pendiente'), ('reconciled', 'Conciliada con proveedor'),
        ('other', 'Revisar / otro destino'),
    ], compute='_compute_witann_vendor_reconciliation', store=True,
        string='Conciliación con proveedor', index=True)

    @api.depends(
        'pos_session_id', 'amount', 'journal_id.type', 'journal_id.suspense_account_id',
        'journal_id.default_account_id', 'move_id.state',
        'move_id.line_ids.account_id', 'move_id.line_ids.balance',
        'move_id.line_ids.amount_residual', 'move_id.line_ids.amount_residual_currency',
        'move_id.line_ids.matched_credit_ids.credit_move_id.move_id.move_type',
        'move_id.line_ids.matched_debit_ids.debit_move_id.move_id.move_type',
    )
    def _compute_witann_vendor_reconciliation(self):
        for line in self:
            liquidity, suspense, other = line._seek_for_lines()
            counterparts = (
                other.matched_credit_ids.credit_move_id
                | other.matched_debit_ids.debit_move_id)
            bills = counterparts.move_id.filtered(lambda m: m.move_type == 'in_invoice')
            line.witann_vendor_bill_ids = bills
            is_cash_out = (line.pos_session_id and line.amount < 0
                           and line.journal_id.type == 'cash' and line.state == 'posted')
            plain_suspense = (
                len(liquidity) == 1 and len(suspense) == 1 and not other
                and not (suspense.matched_credit_ids | suspense.matched_debit_ids))
            paid_payables = (
                other and all(aml.account_id.account_type == 'liability_payable'
                              and aml.reconciled for aml in other))
            if is_cash_out and plain_suspense:
                line.witann_vendor_reconciliation_state = 'pending'
            elif is_cash_out and bills and not suspense and paid_payables:
                line.witann_vendor_reconciliation_state = 'reconciled'
            else:
                line.witann_vendor_reconciliation_state = 'other'

    def _witann_check_accountant(self):
        if not self.env.user.has_group('account.group_account_user'):
            raise AccessError(_('Solo un usuario de Contabilidad puede conciliar salidas de efectivo.'))
        self.check_access('write')

    def action_witann_reconcile_vendor(self):
        self.ensure_one()
        self._witann_check_accountant()
        if self.witann_vendor_reconciliation_state != 'pending':
            raise UserError(_('La salida ya tiene una conciliación o un destino contable.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Conciliar efectivo con proveedor'),
            'res_model': 'witann.pos.cash.vendor.reconcile',
            'view_mode': 'form', 'target': 'new',
            'context': {'default_statement_line_id': self.id},
        }

    def _witann_lock_reconciliation(self, bills):
        """Version the accounting rows so concurrent stale requests are retried by Odoo.

        A bare FOR UPDATE is insufficient under REPEATABLE READ if a second
        request has already read the old residuals. No-op updates force a
        serialization failure rather than allow two allocations of the same cash.
        """
        moves = self.move_id | bills
        moves.check_access('write')
        amls = moves.line_ids
        amls.check_access('write')
        self.env.flush_all()
        for aml_id in sorted(amls.ids):
            self.env.cr.execute(SQL(
                'UPDATE account_move_line SET write_date = write_date WHERE id = %s', aml_id))
        self.env.invalidate_all()

    def _witann_reconcile_vendor_bills(self, allocations):
        # Wizard defaults must not become defaults on native accounting entries
        # (notably cash-basis tax moves created while reconciling a parent bill).
        self = self.with_context(clean_context(self.env.context))
        allocations = [(bill.with_env(self.env), amount) for bill, amount in allocations]
        self.ensure_one()
        self._witann_check_accountant()
        if not allocations:
            raise UserError(_('Agrega al menos una factura.'))
        bill_ids = [bill.id for bill, amount in allocations]
        bills = self.env['account.move'].browse(bill_ids).exists()
        if len(set(bill_ids)) != len(allocations) or len(bills) != len(allocations):
            raise UserError(_('Selecciona cada factura una sola vez y verifica que exista.'))
        self._witann_lock_reconciliation(bills)
        if (self.witann_vendor_reconciliation_state != 'pending'
                or self.journal_id != self.pos_session_id.cash_journal_id):
            raise UserError(_('La salida no es una salida de caja pendiente de esta sesión.'))
        if self.company_id not in self.env.companies:
            raise UserError(_('Activa la empresa de la salida de efectivo.'))
        currency = self.currency_id
        if currency != self.company_id.currency_id or self.foreign_currency_id:
            raise UserError(_('Esta conciliación requiere efectivo en la moneda de la empresa.'))
        if len(bills.commercial_partner_id) != 1:
            raise UserError(_('Todas las facturas deben ser del mismo proveedor.'))
        partner = bills.commercial_partner_id
        accounting_company = self.company_id.root_id
        if partner.company_id and partner.company_id.root_id != accounting_company:
            raise UserError(_('El proveedor debe ser compartido o pertenecer a la misma empresa matriz.'))
        total = 0.0
        validated = []
        for bill, amount in allocations:
            if (bill.state != 'posted' or bill.move_type != 'in_invoice'
                    or bill.company_id.root_id != accounting_company or bill.currency_id != currency):
                raise UserError(_(
                    'Selecciona facturas publicadas de proveedor de la misma empresa matriz '
                    'o sus sucursales, en la moneda de la salida.'))
            if not math.isfinite(amount) or currency.compare_amounts(amount, 0) <= 0:
                raise UserError(_('Cada importe debe ser positivo.'))
            if not math.isclose(amount, currency.round(amount), rel_tol=0, abs_tol=1e-9):
                raise UserError(_('Los importes deben respetar los decimales de la moneda.'))
            if currency.compare_amounts(amount, bill.amount_residual) > 0:
                raise UserError(_('El importe supera el saldo pendiente de %s.', bill.display_name))
            payable = bill.line_ids.filtered(
                lambda aml: aml.account_id.account_type == 'liability_payable'
                and not aml.reconciled)
            if (len(payable.account_id) != 1 or not payable.account_id.reconcile
                    or any(aml.balance >= 0 for aml in payable)):
                raise UserError(_('La factura requiere revisión de sus partidas por pagar.'))
            if not payable.account_id.filtered_domain(
                    payable.account_id._check_company_domain(self.company_id)):
                raise UserError(_('La cuenta por pagar de la factura no está disponible para la sucursal de la salida.'))
            validated.append((bill, currency.round(amount), payable))
            total += currency.round(amount)
        if currency.compare_amounts(total, -self.amount) != 0:
            raise UserError(_('Distribuye exactamente el importe de la salida entre las facturas.'))

        # Replace only the suspense counterpart of the existing cash entry.
        # The original liquidity line, cash amount, date and session remain intact.
        liquidity, suspense, other = self._seek_for_lines()
        commands = []
        for index, (bill, amount, payable) in enumerate(validated):
            values = {
                'account_id': payable.account_id.id,
                'partner_id': partner.id,
                'currency_id': currency.id,
                'amount_currency': amount, 'debit': amount, 'credit': 0,
                'name': _('Efectivo POS: %s', bill.display_name),
            }
            commands.append(Command.update(suspense.id, values) if index == 0
                            else Command.create(values))
        # Keep the cash-movement label and cashier partner untouched. Changing
        # the statement partner would regenerate its original suspense lines.
        # Native statement reconciliation also permits editing the counterpart
        # of a posted cash entry. Fiscal locks and integrity hashes still apply.
        self.move_id.with_context(skip_readonly_check=True).write({'line_ids': commands})
        payable_lines = self.move_id.line_ids - liquidity
        for (bill, amount, payable), counterpart in zip(validated, payable_lines.sorted('id')):
            (counterpart | payable.sorted(lambda aml: (aml.date_maturity or aml.date, aml.id))).reconcile()
            if not counterpart.reconciled:
                raise UserError(_('No se pudo aplicar todo el importe a %s.', bill.display_name))
            bill.message_post(body=_(
                'Pago en efectivo conciliado desde la sesión POS %(session)s. '
                'Salida: %(reference)s. Importe: %(amount)s %(currency)s.',
                session=self.pos_session_id.name, reference=self.payment_ref,
                amount=amount, currency=currency.name))
        self.move_id.write({'checked': True})
        self.move_id.message_post(body=_(
            'Salida de efectivo %(reference)s conciliada con: %(bills)s. '
            'Total: %(amount)s %(currency)s.', reference=self.payment_ref,
            bills=', '.join(bills.mapped('name')), amount=total, currency=currency.name))

    def action_witann_undo_vendor_reconciliation(self):
        # Native undo can create reversing tax entries as well.
        self = self.with_context(clean_context(self.env.context))
        self.ensure_one()
        self._witann_check_accountant()
        self._witann_lock_reconciliation(self.witann_vendor_bill_ids)
        if not self.witann_vendor_bill_ids:
            raise UserError(_('No hay facturas de proveedor conciliadas con esta salida.'))
        bills = self.witann_vendor_bill_ids
        self.action_undo_reconciliation()
        message = _('Se deshizo la conciliación de la salida de efectivo %(reference)s de la sesión %(session)s.',
                    reference=self.payment_ref, session=self.pos_session_id.name)
        self.move_id.message_post(body=message)
        for bill in bills:
            bill.message_post(body=message)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.ondelete(at_uninstall=False)
    def _witann_check_reconciled_cash_unlink(self):
        if any(line.witann_vendor_bill_ids for line in self):
            raise UserError(_('Deshaz la conciliación con proveedor antes de eliminar la salida.'))
