import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    wgs_curp = fields.Char(
        string='CURP',
        copy=False,
        index=True,
        help='CURP normalizada para validaciones de membresias y control de elegibilidad.',
    )

    @api.model
    def _wgs_normalize_curp(self, value):
        if not value:
            return False
        normalized = re.sub(r'[\s-]+', '', str(value)).upper()
        return normalized or False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'wgs_curp' in vals:
                vals['wgs_curp'] = self._wgs_normalize_curp(vals.get('wgs_curp'))
        return super().create(vals_list)

    def write(self, vals):
        if 'wgs_curp' in vals:
            vals = dict(vals)
            vals['wgs_curp'] = self._wgs_normalize_curp(vals.get('wgs_curp'))
        return super().write(vals)

    @api.constrains('wgs_curp')
    def _check_wgs_curp_unique(self):
        Partner = self.with_context(active_test=False).sudo()
        for partner in self.filtered('wgs_curp'):
            duplicate = Partner.search(
                [
                    ('id', '!=', partner.id),
                    ('wgs_curp', '=', partner.wgs_curp),
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
                        'curp': partner.wgs_curp,
                        'partner': duplicate.display_name,
                    }
                )
