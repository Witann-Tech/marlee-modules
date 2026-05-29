from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    wgs_requires_curp = fields.Boolean(
        string='Requiere CURP en POS',
        default=False,
        help='Obliga a capturar o validar la CURP del contacto antes de vender esta suscripción desde Punto de Venta.',
    )
    wgs_student_age_lock = fields.Boolean(
        string='Restringir a estudiante menor de 25 en POS',
        default=False,
        help='Bloquea venta, renovación, reinscripción y upsale en POS si el titular ya cumplió 25 años. '
             'La validación se hace con la CURP del contacto.',
    )
    wgs_requires_family_authorization = fields.Boolean(
        string='Producto familiar con autorización POS',
        default=False,
        help='Requiere autorización por PIN supervisor antes de vender este producto desde Suscripciones POS.',
    )
    wgs_single_day_access = fields.Boolean(
        string='Vigencia de 1 día en POS',
        default=False,
        help='La suscripción vendida desde POS inicia y termina el mismo día, sin programación de siguiente factura.',
    )
    wgs_free_trial_day = fields.Boolean(
        string='Día de prueba gratis en POS',
        default=False,
        help='Disponible una sola vez por CURP. Al venderlo desde POS se crea una vigencia de un solo día.',
    )
    wgs_access_site_ids = fields.Many2many(
        'access_control.site',
        'product_template_wgs_access_site_rel',
        'product_tmpl_id',
        'site_id',
        string='Sitios de acceso WGS',
        help='Si se configuran, la suscripción otorgará acceso únicamente a estos sitios. '
             'Si se dejan vacíos, se mantiene el comportamiento actual por empresa.',
    )
    wgs_access_timezone_id = fields.Many2one(
        'access_control.timezone',
        string='Horario de acceso WGS',
        default=lambda self: self.env.ref('access_control_api.access_timezone_general', raise_if_not_found=False),
        domain="[('active', '=', True)]",
        help='Horario global que se asignará a las personas de control de acceso. '
             'Acceso general usa timezone_id=1.',
    )
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

        res = super().write(vals)
        if 'wgs_access_timezone_id' in vals:
            self._wgs_resync_access_for_timezone_change()
        return res

    def _wgs_resync_access_for_timezone_change(self):
        if 'sale.order.line' not in self.env.registry:
            return False
        variant_ids = self.mapped('product_variant_ids').ids
        if not variant_ids:
            return False
        SaleLine = self.env['sale.order.line'].sudo()
        domain = [('product_id', 'in', variant_ids)]
        if 'display_type' in SaleLine._fields:
            domain.append(('display_type', '=', False))
        if 'order_id' in SaleLine._fields:
            domain.append(('order_id.state', 'in', ('sale', 'done')))
        lines = SaleLine.search(domain)
        orders = lines.mapped('order_id').filtered(lambda order: hasattr(order, '_wgs_sync_access_control_people'))
        if orders:
            orders.with_context(access_sync_priority=True)._wgs_sync_access_control_people()
        return bool(orders)

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
