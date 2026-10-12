from odoo import fields, models


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    witann_bank_movement = fields.Char(
        string='Movimiento bancario', index=True, copy=False,
        help='Identificador MOVIMIENTO del banco, único dentro de este diario.',
    )

    _witann_movement_unique = models.Constraint(
        'UNIQUE (journal_id, witann_bank_movement)',
        'El movimiento bancario ya existe en este diario.',
    )
