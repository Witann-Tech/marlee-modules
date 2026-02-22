from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    max_participants_total = fields.Integer(
        string='Máximo de participantes (total)',
        default=1,
        help='Cantidad total permitida por unidad de suscripción, incluyendo al titular.',
    )

    @api.constrains('max_participants_total', 'recurring_invoice')
    def _check_max_participants_total(self):
        for product in self:
            if product.max_participants_total < 0:
                raise ValidationError(
                    _('El máximo de participantes no puede ser negativo.')
                )
            if product.recurring_invoice and product.max_participants_total < 1:
                raise ValidationError(
                    _('Los productos de suscripción deben permitir al menos 1 participante (titular).')
                )

    def write(self, vals):
        if 'max_participants_total' in vals:
            try:
                new_capacity = int(vals.get('max_participants_total') or 0)
            except (TypeError, ValueError):
                new_capacity = False

            for product in self:
                if new_capacity is False or new_capacity == int(product.max_participants_total or 0):
                    continue
                if product._wgs_has_any_sales_history():
                    raise ValidationError(
                        _(
                            'No puedes modificar el máximo de participantes de "%(product)s" '
                            'porque el producto ya tiene ventas registradas.'
                        )
                        % {'product': product.display_name}
                    )

        return super().write(vals)

    def _wgs_has_any_sales_history(self):
        self.ensure_one()
        variant_ids = self.product_variant_ids.ids
        if not variant_ids:
            return False

        if 'sale.order.line' in self.env.registry:
            sale_line_model = self.env['sale.order.line'].sudo()
            sale_domain = [('product_id', 'in', variant_ids)]
            if 'display_type' in sale_line_model._fields:
                sale_domain.append(('display_type', '=', False))
            if 'state' in sale_line_model._fields:
                sale_domain.append(('state', 'in', ('sale', 'done')))
            elif 'order_id' in sale_line_model._fields:
                sale_domain.append(('order_id.state', 'in', ('sale', 'done')))
            if sale_line_model.search_count(sale_domain):
                return True

        if 'pos.order.line' in self.env.registry:
            pos_line_model = self.env['pos.order.line'].sudo()
            pos_domain = [('product_id', 'in', variant_ids)]
            if 'qty' in pos_line_model._fields:
                pos_domain.append(('qty', '>', 0))
            if 'order_id' in pos_line_model._fields:
                pos_domain.append(('order_id.state', 'not in', ('draft', 'cancel')))
            if pos_line_model.search_count(pos_domain):
                return True

        return False

    @api.model
    def _wgs_patch_recurring_prices_arch(self, arch):
        if not arch:
            return arch

        pricing_model_name = 'product.pricelist.item'
        if pricing_model_name not in self.env.registry:
            return arch
        if 'wgs_minimum_term_periods' not in self.env[pricing_model_name]._fields:
            return arch

        pricing_field_names = {
            field_name
            for field_name, field in self._fields.items()
            if field.type in ('one2many', 'many2many') and getattr(field, 'comodel_name', '') == pricing_model_name
        }
        if not pricing_field_names:
            return arch

        is_element = isinstance(arch, etree._Element)
        doc = arch if is_element else etree.XML(arch)

        # Target inline recurrent pricing editors in product form.
        all_inline_fields = doc.xpath("//field[(./tree or ./list or ./form)]")
        pricing_fields = []
        for node in all_inline_fields:
            field_name = node.get('name')
            if field_name not in pricing_field_names:
                continue
            if not node.xpath("ancestor::page[contains(@name, 'recurr') or contains(@name, 'subscription')]"):
                continue
            pricing_fields.append(node)

        if not pricing_fields:
            return arch

        for pricing_field in pricing_fields:
            for subview_tag in ('tree', 'list', 'form'):
                subviews = pricing_field.xpath(f'./{subview_tag}')
                for subview in subviews:
                    if subview.xpath(".//field[@name='wgs_minimum_term_periods']"):
                        continue
                    new_field = etree.Element('field', name='wgs_minimum_term_periods')
                    anchors = subview.xpath(
                        ".//field[@name='min_quantity' or @name='price' or @name='fixed_price' or @name='plan_id' or @name='recurrence_id']"
                    )
                    if anchors:
                        anchors[-1].addnext(new_field)
                    else:
                        subview.append(new_field)

        if is_element:
            return doc
        return etree.tostring(doc, encoding='unicode')

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        result = super().fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if view_type != 'form' or not result.get('arch'):
            return result
        result['arch'] = self._wgs_patch_recurring_prices_arch(result['arch'])
        return result

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        result = super().get_view(view_id=view_id, view_type=view_type, **options)
        if view_type != 'form' or not result.get('arch'):
            return result
        result['arch'] = self._wgs_patch_recurring_prices_arch(result['arch'])
        return result
