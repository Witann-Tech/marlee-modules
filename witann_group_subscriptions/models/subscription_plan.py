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
    def _wgs_patch_form_arch_with_min_term(self, arch):
        if not arch:
            return arch

        is_element = isinstance(arch, etree._Element)
        doc = arch if is_element else etree.XML(arch)

        if doc.xpath("//field[@name='wgs_minimum_term_periods']"):
            return arch

        field_node = etree.Element('field', name='wgs_minimum_term_periods')
        anchor_candidates = (
            "//field[@name='recurring_interval']",
            "//field[@name='billing_period_value']",
            "//field[@name='name']",
        )
        inserted = False
        for xpath_expr in anchor_candidates:
            anchors = doc.xpath(xpath_expr)
            if not anchors:
                continue
            anchors[-1].addnext(field_node)
            inserted = True
            break

        if not inserted:
            groups = doc.xpath('//sheet//group')
            if groups:
                groups[0].append(field_node)
                inserted = True

        if not inserted:
            return arch

        if is_element:
            return doc
        return etree.tostring(doc, encoding='unicode')

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        result = super().fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if view_type != 'form' or not result.get('arch'):
            return result

        result['arch'] = self._wgs_patch_form_arch_with_min_term(result['arch'])
        return result

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        result = super().get_view(view_id=view_id, view_type=view_type, **options)
        if view_type != 'form' or not result.get('arch'):
            return result
        result['arch'] = self._wgs_patch_form_arch_with_min_term(result['arch'])
        return result
