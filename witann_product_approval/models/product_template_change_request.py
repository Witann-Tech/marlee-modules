from odoo import api, fields, models


class ProductTemplateChangeRequest(models.Model):
    _name = 'product.template.change.request'
    _description = 'Solicitud de cambio de producto'
    _order = 'create_date desc'

    name = fields.Char(
        string='Referencia',
        compute='_compute_name',
        store=True,
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Producto',
        required=True,
        ondelete='cascade',
        index=True,
    )
    change_type = fields.Selection(
        [('create', 'Alta'), ('update', 'Cambio')],
        string='Tipo',
        required=True,
        default='update',
    )
    state = fields.Selection(
        [('pending', 'Pendiente'), ('approved', 'Aprobada'), ('rejected', 'Rechazada')],
        string='Estado',
        required=True,
        default='pending',
        index=True,
    )
    payload = fields.Json(
        string='Cambios propuestos',
        default=dict,
        required=True,
        readonly=True,
    )
    requested_by_id = fields.Many2one(
        'res.users',
        string='Solicitado por',
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    requested_on = fields.Datetime(
        string='Fecha solicitud',
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )
    approved_by_id = fields.Many2one(
        'res.users',
        string='Aprobado por',
        readonly=True,
    )
    approved_on = fields.Datetime(
        string='Fecha aprobación',
        readonly=True,
    )
    rejected_by_id = fields.Many2one(
        'res.users',
        string='Rechazado por',
        readonly=True,
    )
    rejected_on = fields.Datetime(
        string='Fecha rechazo',
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        related='product_tmpl_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )

    @api.depends('change_type', 'product_tmpl_id.display_name', 'create_date')
    def _compute_name(self):
        for record in self:
            label = 'Alta' if record.change_type == 'create' else 'Cambio'
            display_name = record.product_tmpl_id.display_name or 'Producto'
            record.name = f'{label}: {display_name}'
