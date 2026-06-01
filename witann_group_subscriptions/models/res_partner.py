import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    _WGS_CURP_FIELD = 'x_studio_curp'
    _WGS_CURP_SYNC_CONTEXT_KEY = 'wgs_skip_curp_storage_sync'
    _WGS_PACKAGE_SYNC_CONTEXT_KEY = 'wgs_skip_subscription_package_sync'

    wgs_subscription_package_names = fields.Char(
        string='Paquete contratado',
        index=True,
        copy=False,
        readonly=True,
    )

    def _wgs_get_subscription_package_names(self):
        self.ensure_one()
        SaleOrder = self.env['sale.order'].sudo()
        if not hasattr(SaleOrder, '_wgs_get_related_subscription_orders_for_partner'):
            return []

        package_names = []
        seen_names = set()
        orders = SaleOrder._wgs_get_related_subscription_orders_for_partner(self)
        for order in orders:
            if not order._wgs_classify_subscription_access_state():
                continue
            for line in order._get_subscription_recurring_lines():
                product = line.product_id
                product_tmpl = product.product_tmpl_id if product else False
                package_name = product_tmpl.display_name if product_tmpl else (product.display_name if product else False)
                if not package_name or package_name in seen_names:
                    continue
                seen_names.add(package_name)
                package_names.append(package_name)
        return package_names

    def _wgs_refresh_subscription_package_names(self):
        if self.env.context.get(self._WGS_PACKAGE_SYNC_CONTEXT_KEY):
            return
        for partner in self:
            package_names = ', '.join(partner._wgs_get_subscription_package_names())
            if (partner.wgs_subscription_package_names or '') == package_names:
                continue
            super(
                ResPartner,
                partner.with_context(**{self._WGS_PACKAGE_SYNC_CONTEXT_KEY: True}).sudo(),
            ).write({'wgs_subscription_package_names': package_names or False})

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
        result = super().write(self._wgs_normalize_curp_in_vals(vals))
        self._wgs_sync_curp_storage()
        self._wgs_check_curp_uniqueness()
        return result
