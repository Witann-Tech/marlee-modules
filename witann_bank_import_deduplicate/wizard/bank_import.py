import base64
import binascii
from collections import Counter, defaultdict
from dataclasses import replace

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.fields import Command

from ..deduplicate import Existing, classify
from ..contacts import MAX_PARTNERS, Contact, Matcher, Partner, extract_contact, normalize_name
from ..parser import FileError, MAX_FILE_BYTES, parse_file


class BankImport(models.TransientModel):
    _name = 'witann.bank.import'
    _description = 'Importar movimientos sin duplicados'
    _check_company_auto = True

    journal_id = fields.Many2one(
        'account.journal', string='Diario bancario', required=True,
        domain="[('type', '=', 'bank')]", check_company=True,
    )
    company_id = fields.Many2one(related='journal_id.company_id')
    file_data = fields.Binary(string='Archivo CSV/XLSX', required=True, attachment=False)
    filename = fields.Char(string='Nombre del archivo', required=True)
    state = fields.Selection([
        ('draft', 'Archivo'), ('analyzed', 'Analizado'), ('done', 'Finalizado'),
    ], default='draft', required=True, readonly=True)
    read_count = fields.Integer(string='Leídas', readonly=True)
    new_count = fields.Integer(string='Nuevas', readonly=True)
    existing_count = fields.Integer(string='Existentes', readonly=True)
    duplicate_count = fields.Integer(string='Repeticiones', readonly=True)
    conflict_count = fields.Integer(string='Conflictos', readonly=True)
    invalid_count = fields.Integer(string='Errores', readonly=True)
    created_count = fields.Integer(string='Creadas', readonly=True)
    skipped_count = fields.Integer(string='Omitidas', readonly=True)
    message = fields.Text(string='Resultado', readonly=True)
    legacy_warning = fields.Text(string='Identificación histórica', readonly=True)
    result_ids = fields.One2many('witann.bank.import.result', 'wizard_id', string='Detalle', readonly=True)
    created_line_ids = fields.Many2many(
        'account.bank.statement.line', string='Movimientos creados', readonly=True,
    )

    @api.onchange('file_data', 'filename', 'journal_id')
    def _onchange_source(self):
        self.state = 'draft'
        self.result_ids = [Command.clear()]
        self.message = False
        self.legacy_warning = False
        for name in (
            'read_count', 'new_count', 'existing_count', 'duplicate_count',
            'conflict_count', 'invalid_count', 'created_count', 'skipped_count',
        ):
            self[name] = 0
        self.created_line_ids = [Command.clear()]

    def _configuration(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('account.group_account_basic'):
            raise AccessError(_('Se requieren permisos de contabilidad bancaria.'))
        journal = self.journal_id
        journal.check_access('read')
        if not journal or journal.type != 'bank':
            raise UserError(_('Selecciona un diario bancario.'))
        if journal.company_id not in self.env.companies:
            raise AccessError(_('Activa la empresa del diario antes de importar.'))
        currency = journal.currency_id or journal.company_id.currency_id
        if not journal.default_account_id or not journal.suspense_account_id:
            raise UserError(_('Configura las cuentas de banco y transitoria del diario.'))
        # Isolate native creation from default_* and reconciliation flags inherited
        # from whichever screen opened the wizard. Keep accounting ACLs/rules.
        lines = self.env['account.bank.statement.line'].with_context({
            'allowed_company_ids': [journal.company_id.id],
            'lang': self.env.lang,
            'tz': self.env.user.tz,
        }).with_company(journal.company_id)
        lines.check_access('read')
        lines.check_access('create')
        return journal, currency, lines

    def _existing(self, lines, journal, movements):
        """Batch lookups. Never backfill identifiers on old accounting records."""
        if not movements:
            return {}
        scope = [('journal_id', '=', journal.id), ('company_id', '=', journal.company_id.id)]
        # Existence-only probes are confined to this authorized journal/company.
        # Reapply the caller's access rules BEFORE reading any target fields; a
        # hidden existing line must block rather than be misclassified as new.
        current = lines.sudo().search(scope + [
            ('witann_bank_movement', 'in', list(movements)),
        ]).with_env(lines.env)
        current.check_access('read')
        found = defaultdict(dict)
        for line in current:
            found[line.witann_bank_movement][line.id] = Existing(
                line.id, line.date, line.amount, line.witann_bank_movement or '',
            )

        # ir.model.data is not readable by ordinary accountants in Odoo 19.
        # Elevation is confined to exact __import__ metadata names for this model.
        # Target records must pass the caller's company and record rules.
        metadata = self.env['ir.model.data'].sudo().search_read([
            ('module', '=', '__import__'),
            ('model', '=', 'account.bank.statement.line'),
            ('name', 'in', list(movements)),
        ], ['name', 'res_id'])
        legacy = lines.sudo().search(scope + [
            ('id', 'in', [item['res_id'] for item in metadata]),
        ]).with_env(lines.env)
        legacy.check_access('read')
        by_id = {line.id: line for line in legacy}
        for item in metadata:
            line = by_id.get(item['res_id'])
            if line is None:
                continue  # missing record or different journal/company
            found[item['name']].setdefault(line.id, Existing(
                line.id, line.date, line.amount, line.witann_bank_movement or '', True,
            ))
        identities = defaultdict(set)
        for movement, candidates in found.items():
            for line_id in candidates:
                identities[line_id].add(movement)
        return {
            key: [replace(item, ambiguous=len(identities[item.id]) > 1) for item in value.values()]
            for key, value in found.items()
        }

    def _analyze(self, configuration):
        journal, currency, lines = configuration
        encoded = self.with_context(bin_size=False).file_data
        if not encoded or not self.filename:
            raise FileError('Selecciona un archivo CSV o XLSX.')
        if len(encoded) > (MAX_FILE_BYTES + 2) // 3 * 4:
            raise FileError('El archivo supera 10 MiB.')
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise FileError('No se pudo decodificar el archivo.') from exc
        parsed = parse_file(data, self.filename, currency=currency.name)
        existing = self._existing(lines, journal, {row.movement for row in parsed.rows})
        results = classify(parsed.rows, existing, currency.compare_amounts)
        return parsed, results

    def _show(self, parsed=None, results=(), *, error=None, created=None):
        counts = Counter(item.status for item in results)
        issues = parsed.issues if parsed else []
        detail = [{
            'row_number': item.row.number,
            'movement': item.row.movement,
            'date': item.row.date,
            'amount': float(item.row.amount),
            'status': 'created' if created is not None and item.status == 'new' else item.status,
            'message': _('Movimiento creado.') if created is not None and item.status == 'new' else item.message,
        } for item in results]
        detail.extend({
            'row_number': issue.number, 'movement': issue.movement,
            'status': 'invalid', 'message': issue.message,
        } for issue in issues)
        if error:
            detail.append({'row_number': 0, 'status': 'invalid', 'message': error})
        blocked = bool(issues or error or counts['conflict'])
        done = created is not None
        self.write({
            'state': 'done' if done else 'analyzed',
            'read_count': parsed.read_count if parsed else 0,
            'new_count': counts['new'],
            'existing_count': counts['existing'],
            'duplicate_count': counts['duplicate'],
            'conflict_count': counts['conflict'],
            'invalid_count': len(issues) + bool(error),
            'created_count': len(created) if done else 0,
            'skipped_count': counts['existing'] + counts['duplicate'],
            'created_line_ids': [Command.set(created.ids if done else [])],
            'result_ids': [Command.clear()] + [Command.create(value) for value in sorted(detail, key=lambda value: value['row_number'])],
            'message': (
                _('Importación finalizada. Se crearon %(created)s y se omitieron %(skipped)s filas.',
                  created=len(created), skipped=counts['existing'] + counts['duplicate']) if done
                else _('Importación bloqueada. Corrige los errores y conflictos indicados.') if blocked
                else _('Análisis completo. Puedes importar los movimientos nuevos.')
            ),
            'legacy_warning': _(
                'Los movimientos antiguos sin MOVIMIENTO sólo se reconocen mediante los IDs externos '
                '__import__.MOVIMIENTO, verificando el diario, '
                'empresa, fecha e importe. Sin un identificador verificable no se pueden deduplicar; '
                'no se infiere identidad por fecha e importe. Otros prefijos requieren revisión en staging.'
            ),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Importar movimientos sin duplicados'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_analyze(self):
        configuration = self._configuration()
        if self.state == 'done':
            raise UserError(_('Esta importación finalizó. Abre un asistente nuevo para otro archivo.'))
        try:
            parsed, results = self._analyze(configuration)
        except FileError as exc:
            return self._show(error=str(exc))
        return self._show(parsed, results)

    def action_import(self):
        configuration = self._configuration()
        if self.state == 'done':
            raise UserError(_('Esta importación finalizó. Abre un asistente nuevo para otro archivo.'))
        try:
            parsed, results = self._analyze(configuration)
        except FileError as exc:
            return self._show(error=str(exc))
        if parsed.issues or any(item.status == 'conflict' for item in results):
            return self._show(parsed, results)
        journal, currency, lines = configuration
        new_rows = [item.row for item in results if item.status == 'new']
        new_movements = {row.movement for row in new_rows}
        contact_rows = [item.row for item in results if item.row.movement in new_movements]
        partner_values = self._partner_values(contact_rows, journal) if new_rows else {}
        values = [{
            'journal_id': journal.id,
            'company_id': journal.company_id.id,
            'statement_id': False,
            'witann_bank_movement': row.movement,
            'date': row.date,
            'amount': currency.round(float(row.amount)),
            'ref': row.reference or False,
            'payment_ref': row.label,
            **partner_values.get(row.number, {}),
        } for row in new_rows]
        try:
            # Any collision rolls back the WHOLE creation batch, including native
            # moves and move lines. Never retry against a stale PG snapshot here.
            with self.env.cr.savepoint():
                created = lines.create(values) if values else lines.browse()
                for line, row in zip(created, new_rows):
                    if line.date != row.date or currency.compare_amounts(line.amount, float(row.amount)):
                        raise UserError(_(
                            'Odoo ajustó la fecha o el importe de la fila %(row)s. '
                            'Se revirtió el lote completo. Revisa el período contable y la configuración del diario.',
                            row=row.number,
                        ))
        except IntegrityError as exc:
            if exc.diag.constraint_name != 'account_bank_statement_line_witann_movement_unique':
                raise
            raise UserError(_(
                'Otra importación creó uno de estos movimientos al mismo tiempo. '
                'Este intento se revirtió por completo. Vuelve a analizar e importar.'
            )) from exc
        # Serialization/deadlock errors intentionally propagate to Odoo's native
        # transaction retry service. No commit and no local snapshot refresh.
        return self._show(parsed, results, created=created)

    def _partner_values(self, rows, journal):
        """Optional enrichment, only for new lines; never create/update contacts."""
        contacts = {row.number: extract_contact(row.detail, row.amount) for row in rows}
        identities = defaultdict(set)
        for row in rows:
            contact = contacts[row.number]
            identities[row.movement].add((normalize_name(contact.name), contact.rfc))
        for row in rows:
            if len(identities[row.movement]) > 1:
                contacts[row.number] = Contact()
        values = {number: {'partner_name': contact.name} for number, contact in contacts.items() if contact.name}
        if not any(contact.name or contact.rfc for contact in contacts.values()):
            return values
        partners = self.env['res.partner'].with_context({
            'allowed_company_ids': [journal.company_id.id],
            'active_test': True,
        }).with_company(journal.company_id)
        try:
            # Normal ACLs/rules, current company or shared commercial contacts.
            # A truncated catalogue cannot establish uniqueness: skip enrichment.
            with self.env.cr.savepoint():
                catalogue = partners.search_read([
                    ('active', '=', True), ('type', '=', 'contact'),
                    ('company_id', 'in', [False, journal.company_id.id]),
                    '|', ('parent_id', '=', False), ('is_company', '=', True),
                ], ['name', 'vat'], limit=MAX_PARTNERS + 1)
        except (AccessError, MissingError):
            return values
        if len(catalogue) > MAX_PARTNERS:
            return values
        matcher = Matcher([Partner(item['id'], item['name'] or '', item['vat'] or '') for item in catalogue])
        for number, contact in contacts.items():
            partner_id = matcher.match(contact)
            if partner_id:
                values.setdefault(number, {})['partner_id'] = partner_id
        return values

    def action_open_created(self):
        self.ensure_one()
        self.check_access('read')
        self.created_line_ids.check_access('read')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Movimientos creados'),
            'res_model': 'account.bank.statement.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.created_line_ids.ids)],
            'context': {'create': False},
        }


class BankImportResult(models.TransientModel):
    _name = 'witann.bank.import.result'
    _description = 'Resultado por fila de la importación bancaria'
    _order = 'row_number, id'

    wizard_id = fields.Many2one('witann.bank.import', required=True, ondelete='cascade', index=True)
    row_number = fields.Integer(string='Fila')
    movement = fields.Char(string='MOVIMIENTO')
    date = fields.Date(string='Fecha')
    amount = fields.Float(string='Importe', digits=(16, 6))
    status = fields.Selection([
        ('new', 'Nueva'), ('existing', 'Existente'), ('duplicate', 'Repetición'),
        ('conflict', 'Conflicto'), ('invalid', 'Inválida'), ('created', 'Creada'),
    ], string='Estado', required=True)
    message = fields.Char(string='Motivo')
