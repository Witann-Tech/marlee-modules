import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    _WGS_CURP_FIELD = 'x_studio_curp'
    _WGS_CURP_SYNC_CONTEXT_KEY = 'wgs_skip_curp_storage_sync'
    _WGS_ACCESS_BLOCK_SYNC_CONTEXT_KEY = 'wgs_skip_access_block_sync'
    _WGS_ACCESS_BLOCK_PARAM_PREFIX = 'witann_group_subscriptions.partner_access_block'

    wgs_access_blocked = fields.Boolean(
        string='Acceso SF bloqueado',
        compute='_compute_wgs_access_block',
        help='Bloqueo manual WGS: impide sincronizar acceso aunque exista una suscripción vigente.',
    )
    wgs_access_block_reason = fields.Text(
        string='Motivo de bloqueo SF',
        compute='_compute_wgs_access_block',
    )
    wgs_access_blocked_at = fields.Datetime(
        string='Bloqueado el',
        compute='_compute_wgs_access_block',
    )
    wgs_access_blocked_by_id = fields.Many2one(
        'res.users',
        string='Bloqueado por',
        compute='_compute_wgs_access_block',
    )

    @api.model
    def _wgs_access_block_param_key(self, partner_id, suffix):
        return '%s.%s.%s' % (self._WGS_ACCESS_BLOCK_PARAM_PREFIX, int(partner_id or 0), suffix)

    @api.depends_context('uid')
    def _compute_wgs_access_block(self):
        ICP = self.env['ir.config_parameter'].sudo()
        user_ids = set()
        values_by_partner = {}
        for partner in self:
            blocked = ICP.get_param(partner._wgs_access_block_param_key(partner.id, 'blocked')) == '1'
            reason = ICP.get_param(partner._wgs_access_block_param_key(partner.id, 'reason')) or False
            blocked_at = ICP.get_param(partner._wgs_access_block_param_key(partner.id, 'blocked_at')) or False
            blocked_by_raw = ICP.get_param(partner._wgs_access_block_param_key(partner.id, 'blocked_by_id')) or False
            try:
                blocked_by_id = int(blocked_by_raw or 0)
            except (TypeError, ValueError):
                blocked_by_id = 0
            if blocked_by_id:
                user_ids.add(blocked_by_id)
            values_by_partner[partner.id] = {
                'blocked': blocked,
                'reason': reason,
                'blocked_at': fields.Datetime.to_datetime(blocked_at) if blocked_at else False,
                'blocked_by_id': blocked_by_id,
            }

        users = self.env['res.users'].sudo().browse(sorted(user_ids)).exists()
        users_by_id = {user.id: user for user in users}
        for partner in self:
            values = values_by_partner.get(partner.id, {})
            partner.wgs_access_blocked = bool(values.get('blocked'))
            partner.wgs_access_block_reason = values.get('reason') or False
            partner.wgs_access_blocked_at = values.get('blocked_at') or False
            partner.wgs_access_blocked_by_id = users_by_id.get(values.get('blocked_by_id')) or False

    def _wgs_write_access_block_storage(self, vals):
        block_fields = {
            'wgs_access_blocked',
            'wgs_access_block_reason',
            'wgs_access_blocked_at',
            'wgs_access_blocked_by_id',
        }
        data = {key: vals[key] for key in block_fields if key in vals}
        if not data:
            return False

        ICP = self.env['ir.config_parameter'].sudo()
        for partner in self:
            blocked = bool(data.get('wgs_access_blocked'))
            if not blocked:
                keys = [
                    partner._wgs_access_block_param_key(partner.id, 'blocked'),
                    partner._wgs_access_block_param_key(partner.id, 'reason'),
                    partner._wgs_access_block_param_key(partner.id, 'blocked_at'),
                    partner._wgs_access_block_param_key(partner.id, 'blocked_by_id'),
                ]
                ICP.search([('key', 'in', keys)]).unlink()
                continue

            blocked_at = data.get('wgs_access_blocked_at') or fields.Datetime.now()
            blocked_by = data.get('wgs_access_blocked_by_id') or self.env.user.id
            if isinstance(blocked_by, models.BaseModel):
                blocked_by = blocked_by.id
            ICP.set_param(partner._wgs_access_block_param_key(partner.id, 'blocked'), '1')
            ICP.set_param(partner._wgs_access_block_param_key(partner.id, 'reason'), data.get('wgs_access_block_reason') or '')
            ICP.set_param(
                partner._wgs_access_block_param_key(partner.id, 'blocked_at'),
                fields.Datetime.to_string(fields.Datetime.to_datetime(blocked_at)),
            )
            ICP.set_param(partner._wgs_access_block_param_key(partner.id, 'blocked_by_id'), str(int(blocked_by or 0)))
        return True

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
        access_block_vals = {
            key: normalized_vals.pop(key)
            for key in list(normalized_vals)
            if key in access_block_fields
        }
        before_sync_partner_ids = self.ids if access_block_vals else []
        result = super().write(normalized_vals) if normalized_vals else True
        if access_block_vals:
            self._wgs_write_access_block_storage(access_block_vals)
        self._wgs_sync_curp_storage()
        self._wgs_check_curp_uniqueness()
        if before_sync_partner_ids and not self.env.context.get(self._WGS_ACCESS_BLOCK_SYNC_CONTEXT_KEY):
            sale_order_model = self.env['sale.order'].sudo()
            if hasattr(sale_order_model, '_wgs_sync_access_control_people'):
                sale_order_model.with_context(access_sync_priority=True)._wgs_sync_access_control_people(
                    extra_partner_ids=before_sync_partner_ids,
                )
        return result
