from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.payslip'].search([
        ('witann_pos_period', '!=', False), ('witann_pos_amount', '>', 0),
        ('state', '!=', 'cancel'), ('credit_note', '=', False),
    ])._witann_sync_pos_claims()
