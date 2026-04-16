import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


def normalize_wgs_curp(value):
    if not value:
        return False
    normalized = re.sub(r'[\s-]+', '', str(value)).upper()
    return normalized or False


class WgsPartnerCurp(models.Model):
    _name = 'wgs.partner.curp'
    _description = 'Partner CURP'
    _rec_name = 'curp'

    partner_id = fields.Many2one(
        'res.partner',
        string='Contacto',
        required=True,
        ondelete='cascade',
        index=True,
    )
    curp = fields.Char(
        string='CURP',
        required=True,
        index=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'curp' in vals:
                vals['curp'] = normalize_wgs_curp(vals.get('curp'))
        return super().create(vals_list)

    def write(self, vals):
        if 'curp' in vals:
            vals = dict(vals)
            vals['curp'] = normalize_wgs_curp(vals.get('curp'))
        return super().write(vals)

    @api.constrains('partner_id')
    def _check_unique_partner_id(self):
        Curp = self.sudo()
        for record in self:
            duplicate = Curp.search(
                [
                    ('id', '!=', record.id),
                    ('partner_id', '=', record.partner_id.id),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    _('El contacto %(partner)s ya tiene una CURP registrada.')
                    % {'partner': record.partner_id.display_name}
                )

    @api.constrains('curp')
    def _check_unique_curp(self):
        Curp = self.sudo()
        for record in self.filtered('curp'):
            duplicate = Curp.search(
                [
                    ('id', '!=', record.id),
                    ('curp', '=', record.curp),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    _(
                        'La CURP %(curp)s ya está asignada al contacto %(partner)s. '
                        'No se permiten contactos duplicados con la misma CURP.'
                    )
                    % {
                        'curp': record.curp,
                        'partner': duplicate.partner_id.display_name,
                    }
                )
