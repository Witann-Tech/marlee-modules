from odoo import models


class LoyaltyProgram(models.Model):
    _inherit = 'loyalty.program'

    def _inverse_pos_report_print_id(self):
        loyalty_mail_model = self.env['loyalty.mail']
        for program in self:
            if program.program_type not in ('gift_card', 'ewallet'):
                continue
            if not program.pos_report_print_id:
                continue

            values = {
                'trigger': 'create',
                'pos_report_print_id': program.pos_report_print_id.id,
            }
            if program.mail_template_id:
                values['mail_template_id'] = program.mail_template_id.id

            if program.communication_plan_ids:
                program.communication_plan_ids.write(values)
            else:
                values['program_id'] = program.id
                loyalty_mail_model.create(values)

    def _register_hook(self):
        result = super()._register_hook()
        field = self._fields.get('pos_report_print_id')
        if field:
            field.inverse = type(self)._inverse_pos_report_print_id
        return result
