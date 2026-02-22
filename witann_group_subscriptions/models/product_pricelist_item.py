from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    wgs_minimum_term_periods = fields.Integer(
        string='Plazo mínimo (periodos)',
        compute='_compute_wgs_minimum_term_periods',
        inverse='_inverse_wgs_minimum_term_periods',
        help='Plazo mínimo del plan recurrente relacionado a esta línea.',
    )

    def _wgs_get_subscription_plan(self):
        self.ensure_one()
        preferred_names = ('plan_id', 'subscription_plan_id', 'recurring_plan_id', 'recurrence_id')
        for field_name in preferred_names:
            if field_name not in self._fields:
                continue
            field = self._fields[field_name]
            if field.type != 'many2one':
                continue
            if getattr(field, 'comodel_name', '') != 'sale.subscription.plan':
                continue
            if self[field_name]:
                return self[field_name]

        for field_name, field in self._fields.items():
            if field.type != 'many2one':
                continue
            if getattr(field, 'comodel_name', '') != 'sale.subscription.plan':
                continue
            value = self[field_name]
            if value:
                return value
        return False

    def _compute_wgs_minimum_term_periods(self):
        for line in self:
            plan = line._wgs_get_subscription_plan()
            line.wgs_minimum_term_periods = int(getattr(plan, 'wgs_minimum_term_periods', 0) or 0)

    def _inverse_wgs_minimum_term_periods(self):
        for line in self:
            plan = line._wgs_get_subscription_plan()
            if not plan:
                continue
            plan.wgs_minimum_term_periods = int(line.wgs_minimum_term_periods or 0)

    @api.constrains('wgs_minimum_term_periods')
    def _check_wgs_minimum_term_periods(self):
        for line in self:
            if int(line.wgs_minimum_term_periods or 0) < 0:
                raise ValidationError(_('El plazo mínimo no puede ser negativo.'))

    @api.model
    def _wgs_patch_arch_add_min_term(self, arch, view_type):
        if not arch or view_type not in ('tree', 'list', 'form'):
            return arch

        is_element = isinstance(arch, etree._Element)
        doc = arch if is_element else etree.XML(arch)

        if doc.xpath("//field[@name='wgs_minimum_term_periods']"):
            return arch

        root_tags = ['tree', 'list', 'form']
        roots = []
        for tag in root_tags:
            roots.extend(doc.xpath(f'//{tag}'))
        if not roots:
            roots = [doc]

        for root in roots:
            # Only inject in recurring pricing-like views where plan is present.
            if not root.xpath(".//field[@name='plan_id']"):
                continue
            new_field = etree.Element('field', name='wgs_minimum_term_periods')
            anchors = root.xpath(".//field[@name='min_quantity' or @name='price' or @name='fixed_price']")
            if anchors:
                anchors[-1].addnext(new_field)
            else:
                root.append(new_field)

        if is_element:
            return doc
        return etree.tostring(doc, encoding='unicode')

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        result = super().fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if view_type not in ('tree', 'list', 'form') or not result.get('arch'):
            return result
        result['arch'] = self._wgs_patch_arch_add_min_term(result['arch'], view_type)
        return result

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        result = super().get_view(view_id=view_id, view_type=view_type, **options)
        if view_type not in ('tree', 'list', 'form') or not result.get('arch'):
            return result
        result['arch'] = self._wgs_patch_arch_add_min_term(result['arch'], view_type)
        return result
