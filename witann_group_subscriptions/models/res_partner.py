import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    _WGS_CURP_FIELD = 'x_studio_curp'
    _WGS_CURP_SYNC_CONTEXT_KEY = 'wgs_skip_curp_storage_sync'
    _WGS_ACCESS_BLOCK_SYNC_CONTEXT_KEY = 'wgs_skip_access_block_sync'

    wgs_access_blocked = fields.Boolean(
        string='Acceso SF bloqueado',
        copy=False,
        index=True,
        help='Bloqueo manual WGS: impide sincronizar acceso aunque exista una suscripción vigente.',
    )
    wgs_access_block_reason = fields.Text(string='Motivo de bloqueo SF', copy=False)
    wgs_access_blocked_at = fields.Datetime(string='Bloqueado el', copy=False, readonly=True)
    wgs_access_blocked_by_id = fields.Many2one(
        'res.users',
        string='Bloqueado por',
        copy=False,
        readonly=True,
        ondelete='set null',
    )

    @api.model
    def _wgs_get_curp_field_name(self, vals=None):
        return self._WGS_CURP_FIELD if self._WGS_CURP_FIELD in self._fields else False

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
        normalized_vals = self._wgs_normalize_curp_in_vals(vals)
        access_block_fields = {
            'wgs_access_blocked',
            'wgs_access_block_reason',
            'wgs_access_blocked_at',
            'wgs_access_blocked_by_id',
        }
        before_sync_partner_ids = self.ids if access_block_fields.intersection(normalized_vals) else []
        result = super().write(normalized_vals)
        self._wgs_sync_curp_storage()
        self._wgs_check_curp_uniqueness()
        if before_sync_partner_ids and not self.env.context.get(self._WGS_ACCESS_BLOCK_SYNC_CONTEXT_KEY):
            sale_order_model = self.env['sale.order'].sudo()
            if hasattr(sale_order_model, '_wgs_sync_access_control_people'):
                sale_order_model.with_context(access_sync_priority=True)._wgs_sync_access_control_people(
                    extra_partner_ids=before_sync_partner_ids,
                )
        return result
