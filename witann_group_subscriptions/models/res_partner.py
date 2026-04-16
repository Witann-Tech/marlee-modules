from odoo import api, fields, models

from .res_partner_curp import normalize_wgs_curp


class ResPartner(models.Model):
    _inherit = 'res.partner'

    wgs_curp = fields.Char(
        string='CURP',
        compute='_compute_wgs_curp',
        inverse='_inverse_wgs_curp',
        search='_search_wgs_curp',
        copy=False,
        help='CURP normalizada para validaciones de membresias y control de elegibilidad.',
    )

    def _compute_wgs_curp(self):
        curp_map = {}
        if self.ids:
            curp_records = self.env['wgs.partner.curp'].sudo().search([('partner_id', 'in', self.ids)])
            curp_map = {
                record.partner_id.id: record.curp
                for record in curp_records
                if record.partner_id
            }
        for partner in self:
            partner.wgs_curp = curp_map.get(partner.id, False)

    def _inverse_wgs_curp(self):
        self._wgs_apply_curp_values({partner.id: partner.wgs_curp for partner in self})

    def _search_wgs_curp(self, operator, value):
        normalized = normalize_wgs_curp(value)
        Curp = self.env['wgs.partner.curp'].sudo()

        if operator in ('=', '!=') and not normalized:
            partner_ids = Curp.search([]).mapped('partner_id').ids
            return [('id', 'not in' if operator == '=' else 'in', partner_ids)]

        if not normalized:
            return [('id', '=', 0)]

        if operator not in ('=', '!=', 'like', 'ilike', '=like', '=ilike'):
            operator = '='

        partner_ids = Curp.search([('curp', operator, normalized)]).mapped('partner_id').ids
        if operator == '!=':
            return [('id', 'not in', partner_ids)]
        return [('id', 'in', partner_ids)]

    @property
    def _wgs_curp_model(self):
        return self.env['wgs.partner.curp'].sudo()

    def _wgs_apply_curp_values(self, curp_by_partner_id):
        Curp = self._wgs_curp_model
        existing_records = Curp.search([('partner_id', 'in', self.ids)])
        existing_by_partner = {record.partner_id.id: record for record in existing_records if record.partner_id}

        for partner in self:
            normalized = normalize_wgs_curp(curp_by_partner_id.get(partner.id))
            existing = existing_by_partner.get(partner.id)
            if normalized:
                if existing:
                    existing.write({'curp': normalized})
                else:
                    Curp.create({'partner_id': partner.id, 'curp': normalized})
            elif existing:
                existing.unlink()

    @api.model_create_multi
    def create(self, vals_list):
        curp_values = [vals.pop('wgs_curp', False) for vals in vals_list]
        partners = super().create(vals_list)
        partners._wgs_apply_curp_values(
            {
                partner.id: curp
                for partner, curp in zip(partners, curp_values)
            }
        )
        return partners

    def write(self, vals):
        curp_value = vals.pop('wgs_curp', None) if 'wgs_curp' in vals else None
        result = super().write(vals)
        if curp_value is not None:
            self._wgs_apply_curp_values({partner.id: curp_value for partner in self})
            self.invalidate_recordset(['wgs_curp'])
        return result
