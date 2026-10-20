from odoo import api, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    @api.model_create_multi
    def create(self, vals_list):
        configs = super().create(vals_list)
        self.env['hr.employee'].invalidate_model(['witann_pos_commission_eligible'])
        return configs

    def write(self, vals):
        result = super().write(vals)
        # pos_hr may also add manager employees during an unrelated write.
        self.env['hr.employee'].invalidate_model(['witann_pos_commission_eligible'])
        return result

    def unlink(self):
        result = super().unlink()
        self.env['hr.employee'].invalidate_model(['witann_pos_commission_eligible'])
        return result
