from lxml import etree

from odoo import api, fields, models


class SaleSubscriptionPricing(models.Model):
    _inherit = 'sale.subscription.pricing'

    wgs_minimum_term_periods = fields.Integer(
        string='Plazo mínimo (periodos)',
        compute='_compute_wgs_minimum_term_periods',
        inverse='_inverse_wgs_minimum_term_periods',
        help=(
            'Plazo mínimo configurado en el plan recurrente asociado. '
            'Se edita desde aquí para facilitar la configuración por producto.'
        ),
    )

    def _wgs_get_plan_for_record(self):
        self.ensure_one()
        preferred_names = ('plan_id', 'subscription_plan_id', 'recurring_plan_id')
        for field_name in preferred_names:
            if field_name in self._fields and self[field_name]:
                return self[field_name]

        for field_name, field in self._fields.items():
            if field.type != 'many2one':
                continue
            comodel_name = getattr(field, 'comodel_name', '')
            if comodel_name != 'sale.subscription.plan':
                continue
            if self[field_name]:
                return self[field_name]
        return False

    def _compute_wgs_minimum_term_periods(self):
        for pricing in self:
            plan = pricing._wgs_get_plan_for_record()
            pricing.wgs_minimum_term_periods = int(getattr(plan, 'wgs_minimum_term_periods', 0) or 0)

    def _inverse_wgs_minimum_term_periods(self):
        for pricing in self:
            plan = pricing._wgs_get_plan_for_record()
            if not plan:
                continue
            plan.wgs_minimum_term_periods = int(pricing.wgs_minimum_term_periods or 0)

    @api.model
    def _wgs_patch_view_arch_with_min_term(self, arch, view_type):
        if not arch:
            return arch

        is_element = isinstance(arch, etree._Element)
        doc = arch if is_element else etree.XML(arch)

        if doc.xpath("//field[@name='wgs_minimum_term_periods']"):
            return arch

        field_node = etree.Element('field', name='wgs_minimum_term_periods')
        inserted = False
        anchor_candidates = (
            "//field[@name='plan_id']",
            "//field[@name='subscription_plan_id']",
            "//field[@name='recurring_plan_id']",
            "//field[@name='fixed_price']",
            "//field[@name='price']",
        )
        for xpath_expr in anchor_candidates:
            anchors = doc.xpath(xpath_expr)
            if not anchors:
                continue
            anchors[-1].addnext(field_node)
            inserted = True
            break

        if not inserted and view_type == 'form':
            groups = doc.xpath('//sheet//group')
            if groups:
                groups[0].append(field_node)
                inserted = True

        if not inserted and view_type in ('tree', 'list'):
            roots = doc.xpath('//tree|//list')
            if roots:
                roots[0].append(field_node)
                inserted = True

        if not inserted:
            return arch

        if is_element:
            return doc
        return etree.tostring(doc, encoding='unicode')

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        result = super().fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if view_type not in ('form', 'tree', 'list') or not result.get('arch'):
            return result

        result['arch'] = self._wgs_patch_view_arch_with_min_term(result['arch'], view_type)
        return result

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        result = super().get_view(view_id=view_id, view_type=view_type, **options)
        if view_type not in ('form', 'tree', 'list') or not result.get('arch'):
            return result

        result['arch'] = self._wgs_patch_view_arch_with_min_term(result['arch'], view_type)
        return result
