import re

from odoo import _, api, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    _WGS_CURP_FIELD_CANDIDATES = (
        'x_studio_curp',
    )
    _WGS_CURP_SYNC_CONTEXT_KEY = 'wgs_skip_curp_storage_sync'

    @api.model
    def _wgs_get_curp_field_name(self, vals=None):
        if vals:
            for field_name in vals.keys():
                field = self._fields.get(field_name)
                if field and field.type in ('char', 'text') and 'curp' in field_name.lower():
                    return field_name

        for field_name in self._WGS_CURP_FIELD_CANDIDATES:
            field = self._fields.get(field_name)
            if field and field.type in ('char', 'text'):
                return field_name

        for field_name, field in self._fields.items():
            if field.type in ('char', 'text') and 'curp' in field_name.lower():
                return field_name
        return False

    @api.model
    def _wgs_has_curp_field(self):
        return bool(self._wgs_get_curp_field_name())

    @api.model
    def _wgs_normalize_curp(self, value):
        if not value:
            return False
        normalized = re.sub(r'[\s-]+', '', str(value)).upper()
        return normalized or False

    def _wgs_get_curp_value(self):
        self.ensure_one()
        field_name = self._wgs_get_curp_field_name()
        if not field_name:
            return False
        return self._wgs_normalize_curp(self[field_name])

    def _wgs_normalize_curp_in_vals(self, vals):
        field_name = self._wgs_get_curp_field_name(vals)
        if not field_name or field_name not in vals:
            return vals
        normalized_vals = dict(vals)
        normalized_vals[field_name] = self._wgs_normalize_curp(vals.get(field_name))
        return normalized_vals

    def _wgs_check_curp_uniqueness(self):
        field_name = self._wgs_get_curp_field_name()
        if not field_name:
            return
        Partner = self.with_context(active_test=False).sudo()
        for partner in self:
            curp = partner._wgs_get_curp_value()
            if not curp:
                continue
            duplicate = Partner.search(
                [
                    ('id', '!=', partner.id),
                    (field_name, '=', curp),
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

    def _wgs_sync_curp_storage(self):
        if not self._wgs_has_curp_field() or self.env.context.get(self._WGS_CURP_SYNC_CONTEXT_KEY):
            return
        for partner in self:
            field_name = partner._wgs_get_curp_field_name()
            if not field_name:
                continue
            raw_value = partner[field_name]
            normalized_value = partner._wgs_normalize_curp(raw_value)
            if raw_value == normalized_value:
                continue
            super(
                ResPartner,
                partner.with_context(**{self._WGS_CURP_SYNC_CONTEXT_KEY: True}),
            ).write({field_name: normalized_value})

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create([self._wgs_normalize_curp_in_vals(vals) for vals in vals_list])
        partners._wgs_sync_curp_storage()
        partners._wgs_check_curp_uniqueness()
        return partners

    def write(self, vals):
        result = super().write(self._wgs_normalize_curp_in_vals(vals))
        self._wgs_sync_curp_storage()
        self._wgs_check_curp_uniqueness()
        return result
