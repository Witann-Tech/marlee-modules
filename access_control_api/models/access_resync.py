"""Explicit, device-scoped recovery; ordinary subscription sync stays incremental."""

import hashlib
import json
import uuid
from datetime import timedelta

import requests

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AccessResyncRequest(models.Model):
    _name = 'access_control.resync_request'
    _description = 'Solicitud de recuperacion de acceso'
    _order = 'id desc'

    company_id = fields.Many2one('res.company', required=True, index=True)
    requested_by = fields.Many2one('res.users', required=True)
    expires_at = fields.Datetime(required=True)
    target_ids = fields.One2many('access_control.resync_target', 'request_id')

    @api.model
    def _queue_for_people(self, people, devices, company, requested_by):
        if len(people) * len(devices) > 32:
            raise ValidationError('La recuperacion admite como maximo 32 destinos por solicitud.')
        request = self.sudo().create({
            'company_id': company.id, 'requested_by': requested_by.id,
            'expires_at': fields.Datetime.now() + timedelta(minutes=10),
        })
        Target = self.env['access_control.resync_target'].sudo()
        Change = self.env['access_control.sync_change'].sudo()
        for person in people:
            for device in devices.filtered(lambda item: item.active and item.site_id in person.site_ids):
                values = {
                    'request_id': request.id, 'person_id': person.id, 'device_id': device.id,
                    'global_user_id': person.global_user_id, 'token': uuid.uuid4().hex,
                }
                if not person.active or person.access_state != 'enabled' or not person.global_user_id:
                    values.update(state='failed', error='La persona no tiene acceso vigente habilitado.')
                source = person.face_pic_b64 or person.face_image or person.partner_id.image_1920
                face = person.partner_id._prepare_biometric_face_b64(source, log_context='access_recovery:%s' % person.id)
                timezone = person.access_timezone_id
                if not face:
                    values.update(state='failed', error='Falta una fotografia de rostro valida; registra o actualiza la foto.')
                elif not timezone or not timezone.active:
                    values.update(state='failed', error='La persona no tiene un horario de acceso valido.')
                if values.get('state') != 'failed' and person.face_pic_b64 != face:
                    person.with_context(skip_access_sync_queue=True).write({'face_pic_b64': face, 'face_image': face})
                target = Target.create(values)
                if target.state == 'failed':
                    continue
                target.authorization_hash = target._current_authorization_hash()
                Change.create({
                    'site_id': device.site_id.id, 'device_id': device.id, 'person_id': person.id,
                    'global_user_id': person.global_user_id, 'action': 'upsert',
                    'include_face_pic': True, 'priority': True, 'reason': 'full_access_recovery',
                    'resync_target_id': target.id,
                })
        return request

    def _status_payload(self, refresh=False):
        self.ensure_one()
        if refresh:
            self.target_ids._refresh_from_gateway()
        rows = [{
            'person_id': target.person_id.id, 'name': target.person_id.partner_id.display_name,
            'device_id': target.device_id.id, 'device_name': target.device_id.display_name,
            'state': target.state, 'error': target.error or False,
        } for target in self.target_ids]
        states = {row['state'] for row in rows}
        terminal = {'confirmed', 'failed', 'expired', 'superseded'}
        state = ('failed' if not rows else 'confirmed' if states == {'confirmed'} else
                 'partial' if 'confirmed' in states and states <= terminal else
                 'failed' if states <= terminal else 'pending')
        return {'request_id': self.id, 'state': state, 'targets': rows,
                'expires_at': fields.Datetime.to_string(self.expires_at)}


class AccessResyncTarget(models.Model):
    _name = 'access_control.resync_target'
    _description = 'Resultado de recuperacion por persona y equipo'

    request_id = fields.Many2one('access_control.resync_request', required=True, ondelete='cascade', index=True)
    token = fields.Char(required=True, readonly=True, index=True)
    person_id = fields.Many2one('access_control.person', required=True, ondelete='restrict')
    device_id = fields.Many2one('access_control.device', required=True, ondelete='restrict')
    global_user_id = fields.Integer(required=True)
    state = fields.Selection([(value, label) for value, label in (
        ('queued', 'Preparada en Odoo'), ('sent', 'Enviada al gateway'),
        ('delivered', 'Entregada al equipo, sin confirmacion'), ('confirmed', 'Confirmada por el equipo'),
        ('failed', 'Rechazada'), ('expired', 'Sin confirmacion dentro del plazo'), ('superseded', 'Sustituida'),
    )], required=True, default='queued', index=True)
    error = fields.Char()
    commands = fields.Json()
    authorization_hash = fields.Char(readonly=True)
    _token_unique = models.Constraint('unique(token)', 'El token de recuperacion debe ser unico.')

    def _current_authorization_hash(self):
        self.ensure_one()
        person = self.person_id
        values = [person.id, person.global_user_id, person.active, person.access_state,
                  sorted(person.site_ids.ids), person.authorize_timezone_id,
                  person.access_timezone_id._interval_payload() if person.access_timezone_id else [],
                  hashlib.sha256((person.face_pic_b64 or '').encode()).hexdigest(),
                  self.device_id.id, self.device_id.active, self.device_id.site_id.id,
                  person.id in self.device_id.local_admin_person_ids.ids]
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

    def _recovery_metadata(self, person, device):
        self.ensure_one()
        if (self.person_id != person or self.device_id != device or
                self.global_user_id != person.global_user_id or not person.active or
                person.access_state != 'enabled' or device.site_id not in person.site_ids or
                self.authorization_hash != self._current_authorization_hash()):
            self.write({'state': 'superseded', 'error': 'La identidad o autorizacion cambio desde la solicitud.'})
            return False
        if fields.Datetime.now() >= self.request_id.expires_at:
            if self.state != 'confirmed':
                self.write({'state': 'expired'})
            return False
        if self.state in ('failed', 'expired', 'superseded', 'confirmed'):
            return False
        self.write({'state': 'sent'})
        return {
            'token': self.token, 'expiresAt': self.request_id.expires_at.isoformat(timespec='seconds') + 'Z',
            'intervals': person.access_timezone_id._interval_payload(),
        }

    def _refresh_from_gateway(self):
        pending = self.filtered(lambda target: target.state in ('queued', 'sent', 'delivered'))
        changed = pending.filtered(lambda target: target.authorization_hash != target._current_authorization_hash())
        changed.write({'state': 'superseded', 'error': 'La identidad o autorizacion cambio desde la solicitud.'})
        pending -= changed
        if not pending:
            return
        base_url, token = pending[0].device_id._get_adms_config()
        headers = {'Authorization': 'Bearer %s' % token} if token else {}
        try:
            with requests.Session() as session:
                with session.get(base_url + '/admin/access-resync/status',
                                 params={'tokens': ','.join(pending.mapped('token'))},
                                 headers=headers, timeout=(2, 5)) as response:
                    response.raise_for_status()
                    if len(response.content) > 256 * 1024:
                        raise ValueError('Respuesta de estado demasiado grande.')
                    payload = response.json()
            if not isinstance(payload, list):
                raise ValueError('Respuesta de estado no valida.')
            by_token = {row.get('token'): row for row in payload if isinstance(row, dict)}
            for target in pending:
                row = by_token.get(target.token, {})
                state = row.get('state')
                if state not in ('queued', 'delivered', 'confirmed', 'failed', 'expired', 'superseded'):
                    continue
                if row.get('device_serial') != target.device_id.device_serial or str(row.get('pin')) != str(target.global_user_id):
                    continue
                commands = row.get('commands') or []
                if not isinstance(commands, list) or len(commands) > 4:
                    continue
                if state == 'confirmed' and (len(commands) != 4 or
                        len({command.get('id') for command in commands if isinstance(command, dict)}) != 4 or
                        any(not isinstance(command, dict) or command.get('status') != 'acked' or
                            command.get('ack_return') != '0' for command in commands)):
                    target.error = 'El gateway no acredita los cuatro comandos con Return=0.'
                    continue
                target.write({'state': 'sent' if state == 'queued' else state,
                              'error': str(row.get('error') or '')[:500], 'commands': commands})
        except (requests.RequestException, ValueError):
            # A read timeout/old gateway cannot turn an unconfirmed request into success.
            pending.write({'error': 'El gateway no devolvio confirmacion; consulta de nuevo o verifica su version.'})
        expired = pending.filtered(lambda target: target.state not in ('confirmed', 'failed', 'superseded')
                                   and target.request_id.expires_at <= fields.Datetime.now())
        expired.write({'state': 'expired'})


class AccessSyncChange(models.Model):
    _inherit = 'access_control.sync_change'

    resync_target_id = fields.Many2one('access_control.resync_target', ondelete='set null', index=True)
