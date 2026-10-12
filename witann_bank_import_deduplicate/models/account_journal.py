from odoo import _, models
from odoo.exceptions import AccessError, UserError


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def action_witann_bank_import(self):
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('account.group_account_basic'):
            raise AccessError(_('Se requieren permisos de contabilidad bancaria.'))
        if self.type != 'bank':
            raise UserError(_('Selecciona un diario bancario.'))
        if self.company_id not in self.env.companies:
            raise AccessError(_('Activa la empresa del diario antes de importar.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Importar movimientos sin duplicados'),
            'res_model': 'witann.bank.import',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_journal_id': self.id,
                'allowed_company_ids': self.env.companies.ids,
            },
        }
