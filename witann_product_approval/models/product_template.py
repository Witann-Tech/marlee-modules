from datetime import date, datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_INTERNAL_APPROVAL_FIELDS = {
    'approval_state',
    'approval_requested_by_id',
    'approval_requested_on',
    'approval_approved_by_id',
    'approval_approved_on',
    'last_change_request_id',
}


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    approval_state = fields.Selection(
        [('pending', 'Pendiente'), ('approved', 'Aprobado'), ('rejected', 'Rechazado')],
        string='Estado de autorización',
        compute='_compute_approval_snapshot',
        readonly=True,
    )
    approval_requested_by_id = fields.Many2one(
        'res.users',
        string='Solicitado por',
        compute='_compute_approval_snapshot',
        readonly=True,
    )
    approval_requested_on = fields.Datetime(
        string='Fecha solicitud',
        compute='_compute_approval_snapshot',
        readonly=True,
    )
    approval_approved_by_id = fields.Many2one(
        'res.users',
        string='Aprobado por',
        compute='_compute_approval_snapshot',
        readonly=True,
    )
    approval_approved_on = fields.Datetime(
        string='Fecha aprobación',
        compute='_compute_approval_snapshot',
        readonly=True,
    )
    last_change_request_id = fields.Many2one(
        'product.template.change.request',
        string='Última solicitud',
        compute='_compute_approval_snapshot',
        readonly=True,
    )

    @api.depends_context('uid')
    def _compute_approval_snapshot(self):
        request_model = self.env['product.template.change.request']
        latest_by_product = {}

        if self.ids:
            requests = request_model.search(
                [('product_tmpl_id', 'in', self.ids)],
                order='id desc',
            )
            for req in requests:
                product_id = req.product_tmpl_id.id
                if product_id not in latest_by_product:
                    latest_by_product[product_id] = req

        for product in self:
            latest = latest_by_product.get(product.id)
            if not latest:
                product.approval_state = 'approved'
                product.approval_requested_by_id = False
                product.approval_requested_on = False
                product.approval_approved_by_id = False
                product.approval_approved_on = False
                product.last_change_request_id = False
                continue

            product.approval_state = latest.state
            product.approval_requested_by_id = latest.requested_by_id
            product.approval_requested_on = latest.requested_on
            product.last_change_request_id = latest

            if latest.state == 'approved':
                product.approval_approved_by_id = latest.approved_by_id
                product.approval_approved_on = latest.approved_on
            else:
                product.approval_approved_by_id = False
                product.approval_approved_on = False

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('skip_product_approval'):
            return super().create(vals_list)
        if self._is_approval_admin():
            records = super(ProductTemplate, self.with_context(skip_product_approval=True)).create(vals_list)
            now = fields.Datetime.now()
            request_model = self.env['product.template.change.request']
            for record, vals in zip(records, vals_list):
                request_model.create(
                    {
                        'product_tmpl_id': record.id,
                        'change_type': 'create',
                        'payload': self._sanitize_payload(vals),
                        'state': 'approved',
                        'requested_by_id': self.env.user.id,
                        'requested_on': now,
                        'approved_by_id': self.env.user.id,
                        'approved_on': now,
                    }
                )
            return records

        now = fields.Datetime.now()
        prepared_vals_list = []
        payloads = []

        for vals in vals_list:
            payload = self._sanitize_payload(vals)
            payloads.append(payload)

            prepared_vals = dict(vals)
            if bool(prepared_vals.get('sale_ok', True)):
                prepared_vals['sale_ok'] = False
            if 'available_in_pos' in self._fields and bool(prepared_vals.get('available_in_pos', False)):
                prepared_vals['available_in_pos'] = False

            prepared_vals_list.append(prepared_vals)

        records = super(ProductTemplate, self.with_context(skip_product_approval=True)).create(prepared_vals_list)
        request_model = self.env['product.template.change.request']

        for record, payload in zip(records, payloads):
            request_model.create(
                {
                    'product_tmpl_id': record.id,
                    'change_type': 'create',
                    'payload': payload,
                    'state': 'pending',
                    'requested_by_id': self.env.user.id,
                    'requested_on': now,
                }
            )

        return records

    def write(self, vals):
        if self.env.context.get('skip_product_approval'):
            return super().write(vals)

        if self._is_approval_admin():
            result = super(ProductTemplate, self.with_context(skip_product_approval=True)).write(vals)
            payload = self._sanitize_payload(vals)
            if payload:
                request_model = self.env['product.template.change.request']
                now = fields.Datetime.now()
                for product in self:
                    request_model.create(
                        {
                            'product_tmpl_id': product.id,
                            'change_type': 'update',
                            'payload': payload,
                            'state': 'approved',
                            'requested_by_id': self.env.user.id,
                            'requested_on': now,
                            'approved_by_id': self.env.user.id,
                            'approved_on': now,
                        }
                    )
            return result

        payload = self._sanitize_payload(vals)
        if not payload:
            return super(ProductTemplate, self.with_context(skip_product_approval=True)).write(vals)

        self.check_access_rights('write')
        self.check_access_rule('write')

        request_model = self.env['product.template.change.request']
        now = fields.Datetime.now()

        for product in self:
            request_model.create(
                {
                    'product_tmpl_id': product.id,
                    'change_type': 'update',
                    'payload': payload,
                    'state': 'pending',
                    'requested_by_id': self.env.user.id,
                    'requested_on': now,
                }
            )

        return True

    def action_approve_pending_changes(self):
        if not self._is_approval_admin():
            raise UserError(_('Solo un administrador de productos puede aprobar solicitudes.'))

        request_model = self.env['product.template.change.request']
        now = fields.Datetime.now()

        for product in self:
            pending_requests = request_model.search(
                [('product_tmpl_id', '=', product.id), ('state', '=', 'pending')],
                order='id asc',
            )

            for request in pending_requests:
                write_vals = product._prepare_payload_for_write(request.payload or {})
                if write_vals:
                    super(ProductTemplate, product.with_context(skip_product_approval=True)).write(write_vals)

                request.write(
                    {
                        'state': 'approved',
                        'approved_by_id': self.env.user.id,
                        'approved_on': now,
                    }
                )

        return True

    def action_reject_pending_changes(self):
        if not self._is_approval_admin():
            raise UserError(_('Solo un administrador de productos puede rechazar solicitudes.'))

        request_model = self.env['product.template.change.request']
        now = fields.Datetime.now()

        for product in self:
            pending_requests = request_model.search(
                [('product_tmpl_id', '=', product.id), ('state', '=', 'pending')]
            )
            pending_requests.write(
                {
                    'state': 'rejected',
                    'rejected_by_id': self.env.user.id,
                    'rejected_on': now,
                }
            )

        return True

    def _is_approval_admin(self):
        return self.env.is_superuser() or self.env.user.has_group('product.group_product_manager')

    def _sanitize_payload(self, vals):
        payload = {}
        for field_name, value in vals.items():
            if field_name in _INTERNAL_APPROVAL_FIELDS:
                continue
            if field_name not in self._fields:
                continue
            payload[field_name] = self._serialize_payload_value(value)
        return payload

    def _prepare_payload_for_write(self, payload):
        write_vals = {}
        for field_name, value in payload.items():
            if field_name in _INTERNAL_APPROVAL_FIELDS:
                continue
            if field_name not in self._fields:
                continue
            write_vals[field_name] = value
        return write_vals

    def _serialize_payload_value(self, value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: self._serialize_payload_value(val) for key, val in value.items()}
        if isinstance(value, list):
            return [self._serialize_payload_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._serialize_payload_value(item) for item in value]
        return value
