from odoo import models


class LoyaltyProgram(models.Model):
    _inherit = 'loyalty.program'

    def _witann_resolve_pos_loyalty_mail_template(self):
        self.ensure_one()
        if self.mail_template_id:
            return self.mail_template_id

        xmlids_by_program_type = {
            'gift_card': (
                'loyalty.mail_template_gift_card',
                'pos_loyalty.mail_template_pos_gift_card',
            ),
            'ewallet': (
                'loyalty.mail_template_loyalty_card',
            ),
        }
        for xmlid in xmlids_by_program_type.get(self.program_type, ()):
            template = self.env.ref(xmlid, raise_if_not_found=False)
            if template:
                return template
        return self.env['mail.template']

    def _inverse_pos_report_print_id(self):
        loyalty_mail_model = self.env['loyalty.mail']
        for program in self:
            if program.program_type not in ('gift_card', 'ewallet'):
                continue
            if not program.pos_report_print_id:
                continue

            mail_template = program._witann_resolve_pos_loyalty_mail_template()
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
