import re

from odoo import _, api, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    _WGS_CURP_FIELD = 'x_studio_curp'

    @api.model
    def _wgs_has_curp_field(self):
        return self._WGS_CURP_FIELD in self._fields

    @api.model
    def _wgs_normalize_curp(self, value):
        if not value:
            return False
        normalized = re.sub(r'[\s-]+', '', str(value)).upper()
        return normalized or False

    def _wgs_get_curp_value(self):
        self.ensure_one()
        if not self._wgs_has_curp_field():
            return False
        return self._wgs_normalize_curp(self[self._WGS_CURP_FIELD])

    def _wgs_normalize_curp_in_vals(self, vals):
        if not self._wgs_has_curp_field() or self._WGS_CURP_FIELD not in vals:
            return vals
        normalized_vals = dict(vals)
        normalized_vals[self._WGS_CURP_FIELD] = self._wgs_normalize_curp(vals.get(self._WGS_CURP_FIELD))
        return normalized_vals

    def _wgs_check_curp_uniqueness(self):
        if not self._wgs_has_curp_field():
            return
        Partner = self.with_context(active_test=False).sudo()
        for partner in self:
            curp = partner._wgs_get_curp_value()
            if not curp:
                continue
            duplicate = Partner.search(
                [
                    ('id', '!=', partner.id),
                    (self._WGS_CURP_FIELD, '=', curp),
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
                        'curp': curp,
                        'partner': duplicate.display_name,
                    }
                )

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create([self._wgs_normalize_curp_in_vals(vals) for vals in vals_list])
        partners._wgs_check_curp_uniqueness()
        return partners

    def write(self, vals):
        result = super().write(self._wgs_normalize_curp_in_vals(vals))
        self._wgs_check_curp_uniqueness()
        return result
