from odoo import models


class LoyaltyProgram(models.Model):
    _inherit = 'loyalty.program'

    def _inverse_pos_report_print_id(self):
        if not (self.env.context.get('install_mode') or self.env.context.get('load_data')):
            return super()._inverse_pos_report_print_id()

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

            # During module loading the print report can be written before the
            # computed email template is available on the record.
            if program.communication_plan_ids:
                program.communication_plan_ids.write(values)
            else:
                values['program_id'] = program.id
                loyalty_mail_model.create(values)
