from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleSubscriptionPlan(models.Model):
    _inherit = 'sale.subscription.plan'

    wgs_minimum_term_periods = fields.Integer(
        string='Plazo mínimo (periodos)',
        default=0,
        help=(
            'Cantidad mínima de periodos que debe durar la suscripción para este plan recurrente. '
            'Si es 0, no se exige plazo mínimo.'
        ),
    )

    @api.constrains('wgs_minimum_term_periods')
    def _check_wgs_minimum_term_periods(self):
        for plan in self:
            if int(plan.wgs_minimum_term_periods or 0) < 0:
                raise ValidationError(_('El plazo mínimo no puede ser negativo.'))

    @api.model
    def _wgs_strip_missing_pricing_min_term_field(self, arch):
        if not arch:
            return arch

        # If runtime model does not expose the field, remove it from any embedded subview.
        if 'product.pricelist.item' in self.env.registry and 'wgs_minimum_term_periods' in self.env['product.pricelist.item']._fields:
            return arch

        is_element = isinstance(arch, etree._Element)
        doc = arch if is_element else etree.XML(arch)
        for node in doc.xpath("//field[@name='wgs_minimum_term_periods']"):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
        if is_element:
            return doc
        return etree.tostring(doc, encoding='unicode')

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        result = super().fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if view_type != 'form' or not result.get('arch'):
            return result
        result['arch'] = self._wgs_strip_missing_pricing_min_term_field(result['arch'])
        return result

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        result = super().get_view(view_id=view_id, view_type=view_type, **options)
        if view_type != 'form' or not result.get('arch'):
            return result
        result['arch'] = self._wgs_strip_missing_pricing_min_term_field(result['arch'])
        return result
