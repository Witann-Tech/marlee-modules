from datetime import date, datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_INTERNAL_APPROVAL_FIELDS = {
    'approval_state',
    'approval_requested_by_id',
    'approval_requested_on',
    'approval_approved_by_id',
    'approval_approved_on',
    'pending_sale_ok',
    'pending_available_in_pos',
    'last_change_request_id',
}


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    approval_state = fields.Selection(
        [('pending', 'Pendiente'), ('approved', 'Aprobado'), ('rejected', 'Rechazado')],
        string='Estado de autorización',
        required=True,
        default='approved',
        copy=False,
        index=True,
    )
    approval_requested_by_id = fields.Many2one(
        'res.users',
        string='Solicitado por',
        copy=False,
        readonly=True,
    )
    approval_requested_on = fields.Datetime(
        string='Fecha solicitud',
        copy=False,
        readonly=True,
    )
    approval_approved_by_id = fields.Many2one(
        'res.users',
        string='Aprobado por',
        copy=False,
        readonly=True,
    )
    approval_approved_on = fields.Datetime(
        string='Fecha aprobación',
        copy=False,
        readonly=True,
    )
    pending_sale_ok = fields.Boolean(
        string='Venta al aprobar',
        copy=False,
        help='Valor de venta que se aplicará al aprobar una alta pendiente.',
    )
    pending_available_in_pos = fields.Boolean(
        string='PdV al aprobar',
        copy=False,
        help='Valor de PdV que se aplicará al aprobar una alta pendiente.',
    )
    last_change_request_id = fields.Many2one(
        'product.template.change.request',
        string='Última solicitud',
        copy=False,
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('skip_product_approval') or self._is_approval_admin():
            records = super().create(vals_list)
            if not self.env.context.get('skip_product_approval'):
                records.with_context(skip_product_approval=True)._mark_as_approved()
            return records

        now = fields.Datetime.now()
        prepared_vals_list = []
        payloads = []

        for vals in vals_list:
            payloads.append(self._sanitize_payload(vals))
            prepared_vals = dict(vals)
            prepared_vals['pending_sale_ok'] = bool(prepared_vals.get('sale_ok', True))
            prepared_vals['sale_ok'] = False

            if 'available_in_pos' in self._fields:
                prepared_vals['pending_available_in_pos'] = bool(prepared_vals.get('available_in_pos', False))
                prepared_vals['available_in_pos'] = False

            prepared_vals.update(
                {
                    'approval_state': 'pending',
                    'approval_requested_by_id': self.env.user.id,
                    'approval_requested_on': now,
                    'approval_approved_by_id': False,
                    'approval_approved_on': False,
                }
            )
            prepared_vals_list.append(prepared_vals)

        records = super().create(prepared_vals_list)
        request_model = self.env['product.template.change.request']

        for record, payload in zip(records, payloads):
            request = request_model.create(
                {
                    'product_tmpl_id': record.id,
                    'change_type': 'create',
                    'payload': payload,
                    'state': 'pending',
                    'requested_by_id': self.env.user.id,
                    'requested_on': now,
                }
            )
            record.with_context(skip_product_approval=True).write({'last_change_request_id': request.id})

        return records

    def write(self, vals):
        if self.env.context.get('skip_product_approval'):
            return super().write(vals)

        if self._is_approval_admin():
            result = super().write(vals)
            if self._has_approval_relevant_changes(vals):
                self.with_context(skip_product_approval=True)._mark_as_approved()
            return result

        if not self._has_approval_relevant_changes(vals):
            return super().write(vals)

        self.check_access_rights('write')
        self.check_access_rule('write')

        request_model = self.env['product.template.change.request']
        now = fields.Datetime.now()

        for product in self:
            payload = product._sanitize_payload(vals)
            request = request_model.create(
                {
                    'product_tmpl_id': product.id,
                    'change_type': 'update',
                    'payload': payload,
                    'state': 'pending',
                    'requested_by_id': self.env.user.id,
                    'requested_on': now,
                }
            )

            workflow_vals = {
                'approval_state': 'pending',
                'approval_requested_by_id': self.env.user.id,
                'approval_requested_on': now,
                'approval_approved_by_id': False,
                'approval_approved_on': False,
                'last_change_request_id': request.id,
            }

            if 'sale_ok' in payload:
                workflow_vals['pending_sale_ok'] = bool(payload['sale_ok'])
            if 'available_in_pos' in payload and 'available_in_pos' in product._fields:
                workflow_vals['pending_available_in_pos'] = bool(payload['available_in_pos'])

            super(ProductTemplate, product.with_context(skip_product_approval=True)).write(workflow_vals)

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
            restore_pending_sale_ok = any(req.change_type == 'create' for req in pending_requests)
            restore_pending_pos_ok = any(req.change_type == 'create' for req in pending_requests)

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

            approval_vals = {
                'approval_state': 'approved',
                'approval_requested_by_id': False,
                'approval_requested_on': False,
                'approval_approved_by_id': self.env.user.id,
                'approval_approved_on': now,
                'pending_sale_ok': False,
                'pending_available_in_pos': False,
            }

            if restore_pending_sale_ok:
                approval_vals['sale_ok'] = product.pending_sale_ok
            if restore_pending_pos_ok and 'available_in_pos' in product._fields:
                approval_vals['available_in_pos'] = product.pending_available_in_pos

            super(ProductTemplate, product.with_context(skip_product_approval=True)).write(approval_vals)

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
            super(ProductTemplate, product.with_context(skip_product_approval=True)).write(
                {
                    'approval_state': 'rejected',
                    'approval_approved_by_id': False,
                    'approval_approved_on': False,
                }
            )

        return True

    def _is_approval_admin(self):
        return self.env.is_superuser() or self.env.user.has_group('product.group_product_manager')

    def _has_approval_relevant_changes(self, vals):
        return any(field_name not in _INTERNAL_APPROVAL_FIELDS for field_name in vals)

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

    def _mark_as_approved(self):
        now = fields.Datetime.now()
        for product in self:
            vals = {
                'approval_state': 'approved',
                'approval_requested_by_id': False,
                'approval_requested_on': False,
                'approval_approved_by_id': self.env.user.id,
                'approval_approved_on': now,
                'pending_sale_ok': False,
                'pending_available_in_pos': False,
            }
            super(ProductTemplate, product).write(vals)
