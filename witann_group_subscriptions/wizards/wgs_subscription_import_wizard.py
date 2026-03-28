import base64
import io
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

_logger = logging.getLogger(__name__)

try:
    import openpyxl
    _OPENPYXL_AVAILABLE = True
except ImportError:
    _OPENPYXL_AVAILABLE = False


class WgsSubscriptionImportWizard(models.TransientModel):
    _name = 'wgs.subscription.import.wizard'
    _description = 'Importador de Suscripciones Existentes (WGS)'

    # ── Campos principales ─────────────────────────────────────────────────────

    file_data = fields.Binary(string='Archivo Excel (.xlsx)', required=True)
    file_name = fields.Char(string='Nombre del archivo')
    state = fields.Selection(
        [('draft', 'Cargar archivo'), ('preview', 'Vista previa'), ('done', 'Completado')],
        default='draft',
        string='Estado',
    )
    line_ids = fields.One2many(
        'wgs.subscription.import.line',
        'wizard_id',
        string='Líneas a importar',
    )
    summary = fields.Text(string='Resumen de importación', readonly=True)

    count_ok = fields.Integer(string='Correctas', compute='_compute_counts')
    count_warning = fields.Integer(string='Advertencias', compute='_compute_counts')
    count_error = fields.Integer(string='Errores', compute='_compute_counts')
    count_total = fields.Integer(string='Total', compute='_compute_counts')

    @api.depends('line_ids.status')
    def _compute_counts(self):
        for wiz in self:
            lines = wiz.line_ids
            wiz.count_ok = len(lines.filtered(lambda l: l.status == 'ok'))
            wiz.count_warning = len(lines.filtered(lambda l: l.status == 'warning'))
            wiz.count_error = len(lines.filtered(lambda l: l.status == 'error'))
            wiz.count_total = len(lines)

    # ── Helpers de resolución ──────────────────────────────────────────────────

    def _resolve_partner(self, client_id_raw):
        """Busca el partner por x_studio_id_de_cliente (int o str)."""
        Partner = self.env['res.partner'].sudo()
        try:
            client_int = int(client_id_raw)
        except (TypeError, ValueError):
            client_int = None

        partner = Partner.search(
            [('x_studio_id_de_cliente', '=', client_int or client_id_raw)], limit=1
        )
        return partner

    def _resolve_product(self, plan_name):
        """Busca product.template recurrente por nombre exacto (case-insensitive)."""
        Product = self.env['product.template'].sudo()
        product = Product.search(
            [('name', '=ilike', plan_name.strip()), ('recurring_invoice', '=', True)],
            limit=1,
        )
        return product

    def _resolve_plan(self, rec_plan_name):
        """Busca sale.subscription.plan por nombre exacto (case-insensitive)."""
        Plan = self.env['sale.subscription.plan'].sudo()
        plan = Plan.search([('name', '=ilike', rec_plan_name.strip())], limit=1)
        return plan

    def _resolve_participants(self, participants_raw):
        """
        Separa la cadena de participantes por coma y busca cada uno por nombre.
        Devuelve (found_ids, unresolved_names).
        """
        if not participants_raw:
            return [], []

        Partner = self.env['res.partner'].sudo()
        found_ids = []
        unresolved = []

        names = [n.strip() for n in str(participants_raw).split(',') if n.strip()]
        for name in names:
            partner = Partner.search([('name', '=ilike', name)], limit=1)
            if partner:
                found_ids.append(partner.id)
            else:
                unresolved.append(name)

        return found_ids, unresolved

    def _parse_date(self, value):
        """Normaliza un valor de celda a date."""
        if not value:
            return False
        if hasattr(value, 'date'):
            return value.date()
        return value

    # ── Acción: Cargar vista previa ────────────────────────────────────────────

    def action_load_preview(self):
        self.ensure_one()

        if not _OPENPYXL_AVAILABLE:
            raise UserError(
                _('La librería openpyxl no está disponible. Ejecute: pip install openpyxl')
            )
        if not self.file_data:
            raise UserError(_('Por favor seleccione un archivo Excel.'))

        raw = base64.b64decode(self.file_data)
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception as e:
            raise UserError(_('No se pudo leer el archivo Excel: %s') % str(e))

        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))
        wb.close()

        if not all_rows:
            raise UserError(_('El archivo está vacío.'))

        # ── Mapear columnas por encabezado ─────────────────────────────────────
        headers = [str(h).strip() if h is not None else '' for h in all_rows[0]]
        col = {h: i for i, h in enumerate(headers) if h}

        required_cols = ['ID Cliente', 'PLAN', 'PLAN RECURRENTE', 'Inicio', 'Fin']
        missing = [c for c in required_cols if c not in col]
        if missing:
            raise UserError(
                _('El archivo no tiene las columnas requeridas: %s') % ', '.join(missing)
            )

        has_participants_col = 'PARTICIPANTES' in col

        # ── Limpiar líneas previas ─────────────────────────────────────────────
        self.line_ids.unlink()

        # ── Procesar cada fila ─────────────────────────────────────────────────
        lines_vals = []

        for row_num, row in enumerate(all_rows[1:], start=2):
            client_id_raw = row[col['ID Cliente']]
            if client_id_raw is None:
                continue  # fila vacía

            plan_name = str(row[col['PLAN']] or '').strip()
            rec_plan_name = str(row[col['PLAN RECURRENTE']] or '').strip()
            start_date = self._parse_date(row[col['Inicio']])
            end_date = self._parse_date(row[col['Fin']])
            participants_raw = (
                str(row[col['PARTICIPANTES']] or '').strip()
                if has_participants_col
                else ''
            )

            # Normalizar ID
            try:
                client_id_str = str(int(float(client_id_raw)))
            except (TypeError, ValueError):
                client_id_str = str(client_id_raw).strip()

            status = 'ok'
            messages = []

            # ── Resolver partner ───────────────────────────────────────────────
            partner = self._resolve_partner(client_id_str)
            if not partner:
                status = 'error'
                messages.append(
                    _('Partner no encontrado con x_studio_id_de_cliente = %s') % client_id_str
                )

            # ── Resolver producto ──────────────────────────────────────────────
            product = self._resolve_product(plan_name) if plan_name else None
            if not product:
                status = 'error'
                messages.append(
                    _('Producto recurrente no encontrado: "%s"') % plan_name
                )

            # ── Resolver plan de suscripción ───────────────────────────────────
            plan = self._resolve_plan(rec_plan_name) if rec_plan_name else None
            if not plan:
                status = 'error'
                messages.append(
                    _('Plan de suscripción no encontrado: "%s"') % rec_plan_name
                )

            # ── Validar fechas ─────────────────────────────────────────────────
            if not start_date:
                status = 'error'
                messages.append(_('Fecha de inicio inválida o vacía.'))
            if not end_date:
                status = 'error'
                messages.append(_('Fecha de fin inválida o vacía.'))

            # ── Resolver participantes adicionales ─────────────────────────────
            participant_ids, unresolved_names = self._resolve_participants(participants_raw)
            if unresolved_names:
                if status == 'ok':
                    status = 'warning'
                messages.append(
                    _('Participantes no encontrados por nombre (se omitirán): %s')
                    % ', '.join('"%s"' % n for n in unresolved_names)
                )

            lines_vals.append({
                'wizard_id': self.id,
                'row_number': row_num,
                'client_id_raw': client_id_str,
                'plan_name_raw': plan_name,
                'rec_plan_name_raw': rec_plan_name,
                'start_date': start_date,
                'end_date': end_date,
                'participants_raw': participants_raw,
                'partner_id': partner.id if partner else False,
                'product_tmpl_id': product.id if product else False,
                'plan_id': plan.id if plan else False,
                'participant_ids': [Command.set(participant_ids)] if participant_ids else [],
                'status': status,
                'message': '\n'.join(messages),
            })

        if not lines_vals:
            raise UserError(_('No se encontraron filas con datos en el archivo.'))

        self.env['wgs.subscription.import.line'].create(lines_vals)
        self.state = 'preview'
        return self._reopen_wizard()

    # ── Acción: Importar ───────────────────────────────────────────────────────

    def action_import(self):
        self.ensure_one()

        importable = self.line_ids.filtered(lambda l: l.status in ('ok', 'warning'))
        if not importable:
            raise UserError(_('No hay líneas válidas para importar (solo errores).'))

        SaleOrder = self.env['sale.order']
        created = 0
        skipped = 0
        error_details = []

        for line in importable:
            try:
                with self.env.cr.savepoint():
                    self._import_line(line, SaleOrder)
                    created += 1
                    line.write({'status': 'done', 'message': _('✅ Importada correctamente.')})
            except Exception as exc:
                skipped += 1
                msg = str(exc)
                error_details.append(_('Fila %s (ID %s): %s') % (line.row_number, line.client_id_raw, msg))
                line.write({'status': 'error', 'message': msg})
                _logger.exception('WGS Import: error en fila %s', line.row_number)

        parts = [
            _('Importación completada.'),
            _('✅ Creadas: %d') % created,
            _('❌ Con error: %d') % skipped,
            _('⏭️ Omitidas (error previo): %d') % len(self.line_ids.filtered(lambda l: l.status == 'error' and not l.message.startswith('✅'))),
        ]
        if error_details:
            parts.append('')
            parts.append(_('Detalle de errores:'))
            parts.extend(error_details)

        self.write({'state': 'done', 'summary': '\n'.join(parts)})
        return self._reopen_wizard()

    def _import_line(self, line, SaleOrder):
        """Crea una sale.order de suscripción a partir de una línea validada."""
        product_tmpl = line.product_tmpl_id
        product_variant = product_tmpl.product_variant_id
        if not product_variant:
            raise UserError(
                _('El producto "%s" no tiene variante disponible.') % product_tmpl.display_name
            )

        # ── Crear la orden de venta / suscripción ──────────────────────────────
        order = SaleOrder.with_context(
            skip_owner_participant_sync=True,  # evitar doble sync durante creación
        ).create({
            'partner_id': line.partner_id.id,
            'plan_id': line.plan_id.id,
            'wgs_effective_start_date': line.start_date,
            'next_invoice_date': line.end_date,
            'order_line': [Command.create({
                'product_id': product_variant.id,
                'product_uom_qty': 1,
                'price_unit': 0,  # importación histórica — sin facturación retroactiva
            })],
        })

        # ── Agregar participantes adicionales ──────────────────────────────────
        # El titular se agrega automáticamente mediante _ensure_subscription_owner_is_participant
        if line.participant_ids:
            order.with_context(skip_owner_participant_sync=True).write({
                'participant_ids': [Command.link(pid) for pid in line.participant_ids.ids],
            })

        # ── Confirmar y marcar como suscripción activa ─────────────────────────
        order.action_confirm()

        # Forzar subscription_state = 'progress' (activa) independientemente del flujo
        if 'subscription_state' in order._fields:
            order.write({'subscription_state': 'progress'})

        # ── Sync de control de acceso (dispara al escribir subscription_state) ─
        order._wgs_sync_access_control_people()

    # ── Utilidades ─────────────────────────────────────────────────────────────

    def _reopen_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_reset(self):
        self.line_ids.unlink()
        self.write({'state': 'draft', 'summary': False})
        return self._reopen_wizard()


class WgsSubscriptionImportLine(models.TransientModel):
    _name = 'wgs.subscription.import.line'
    _description = 'Línea de importación de suscripción (WGS)'
    _order = 'row_number asc'

    wizard_id = fields.Many2one(
        'wgs.subscription.import.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )

    # ── Datos crudos del Excel ─────────────────────────────────────────────────
    row_number = fields.Integer(string='Fila', readonly=True)
    client_id_raw = fields.Char(string='ID Cliente', readonly=True)
    plan_name_raw = fields.Char(string='PLAN', readonly=True)
    rec_plan_name_raw = fields.Char(string='PLAN RECURRENTE', readonly=True)
    start_date = fields.Date(string='Inicio', readonly=True)
    end_date = fields.Date(string='Fin', readonly=True)
    participants_raw = fields.Char(string='PARTICIPANTES (texto)', readonly=True)

    # ── Registros resueltos en Odoo ────────────────────────────────────────────
    partner_id = fields.Many2one('res.partner', string='Titular', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', string='Producto', readonly=True)
    plan_id = fields.Many2one('sale.subscription.plan', string='Plan', readonly=True)
    participant_ids = fields.Many2many(
        'res.partner',
        'wgs_import_line_participant_rel',
        'line_id',
        'partner_id',
        string='Participantes resueltos',
        readonly=True,
    )

    # ── Estado de la línea ─────────────────────────────────────────────────────
    status = fields.Selection(
        [
            ('ok', 'Correcto'),
            ('warning', 'Advertencia'),
            ('error', 'Error'),
            ('done', 'Importado'),
        ],
        string='Estado',
        default='ok',
        readonly=True,
    )
    message = fields.Text(string='Notas / Errores', readonly=True)
