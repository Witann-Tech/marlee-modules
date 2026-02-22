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
