try:
    from odoo.addons.pos_loyalty.models import loyalty_program as pos_loyalty_program
except ImportError:  # pragma: no cover - pos_loyalty may be absent in some databases
    pos_loyalty_program = None


def _wplif_inverse_pos_report_print_id(self):
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


if pos_loyalty_program is not None:
    pos_loyalty_program.LoyaltyProgram._inverse_pos_report_print_id = _wplif_inverse_pos_report_print_id
    pos_report_field = pos_loyalty_program.LoyaltyProgram._fields.get('pos_report_print_id')
    if pos_report_field:
        pos_report_field.inverse = _wplif_inverse_pos_report_print_id
