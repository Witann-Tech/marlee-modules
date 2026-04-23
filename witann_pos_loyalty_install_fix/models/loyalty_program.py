from odoo import models


class LoyaltyProgram(models.Model):
    _inherit = 'loyalty.program'

    def _inverse_pos_report_print_id(self):
        loyalty_mail_model = self.env['loyalty.mail']
        xmlids_by_program_type = {
            'gift_card': (
                'loyalty.mail_template_gift_card',
                'pos_loyalty.mail_template_pos_gift_card',
            ),
            'ewallet': (
                'loyalty.mail_template_loyalty_card',
            ),
        }
        for program in self:
            if program.program_type not in ('gift_card', 'ewallet'):
                continue
            if not program.pos_report_print_id:
                continue

            mail_template = program.mail_template_id
            if not mail_template:
                for xmlid in xmlids_by_program_type.get(program.program_type, ()):
                    mail_template = program.env.ref(xmlid, raise_if_not_found=False)
                    if mail_template:
                        break

            values = {
                'trigger': 'create',
                'pos_report_print_id': program.pos_report_print_id.id,
            }
            if mail_template:
                values['mail_template_id'] = mail_template.id

            if program.communication_plan_ids:
                program.communication_plan_ids.write(values)
            elif values.get('mail_template_id'):
                values['program_id'] = program.id
                loyalty_mail_model.create(values)

    def _register_hook(self):
        result = super()._register_hook()
        field = self._fields.get('pos_report_print_id')
        if field:
            field.inverse = type(self)._inverse_pos_report_print_id
        return result
