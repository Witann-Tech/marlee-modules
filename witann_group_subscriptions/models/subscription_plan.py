from lxml import etree

from odoo import api, fields, models


class SaleSubscriptionPlan(models.Model):
    _inherit = 'sale.subscription.plan'

    wgs_single_day_plan = fields.Boolean(
        string='Vigencia de 1 día WGS',
        default=False,
        help='Cuando está activo, Witann Group Subscriptions tratará este plan como una vigencia exacta de un día.',
    )

    @api.model
    def _wgs_strip_removed_min_term_field(self, arch):
        if not arch:
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
        result['arch'] = self._wgs_strip_removed_min_term_field(result['arch'])
        return result

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        result = super().get_view(view_id=view_id, view_type=view_type, **options)
        if view_type != 'form' or not result.get('arch'):
            return result
        result['arch'] = self._wgs_strip_removed_min_term_field(result['arch'])
        return result
