# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class AccessControlApi(http.Controller):

    @http.route(
        '/api/access/validate',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def validate(self, **payload):
        # ---- Auth: Bearer token ----
        auth = request.httprequest.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return {"allowed": False, "reason": "missing_token", "openMs": None}

        token = auth.split(' ', 1)[1].strip()

        expected = request.env['ir.config_parameter'].sudo().get_param('access_control.api_token')
        if not expected:
            return {"allowed": False, "reason": "server_token_not_configured", "openMs": None}

        if token != expected:
            return {"allowed": False, "reason": "invalid_token", "openMs": None}

        # ---- Business: resolve credential by fingerprintId ----
        # Odoo type='json' expects JSON-RPC; payload/params will contain the "params" dict.
        data = request.params or payload or {}

        fingerprint_id = data.get('fingerprintId') or data.get('fingerprint_id')
        if not fingerprint_id:
            return {"allowed": False, "reason": "missing_fingerprint_id", "openMs": None}

        Credential = request.env['access_control.credential'].sudo()
        cred = Credential.search([
            ('fingerprint_id', '=', fingerprint_id),
            ('active', '=', True),
        ], limit=1)

        if not cred:
            return {"allowed": False, "reason": "credential_not_found", "openMs": None}

        return {"allowed": True, "reason": "credential_ok", "openMs": 500}

    @http.route(
        '/api/access/sync_users',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def sync_users(self, **payload):
        # ---- Auth: Bearer token ----
        auth = request.httprequest.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return {"ok": False, "reason": "missing_token", "users": []}

        token = auth.split(' ', 1)[1].strip()

        expected = request.env['ir.config_parameter'].sudo().get_param('access_control.api_token')
        if not expected:
            return {"ok": False, "reason": "server_token_not_configured", "users": []}

        if token != expected:
            return {"ok": False, "reason": "invalid_token", "users": []}

        # ---- Payload ----
        data = request.params or payload or {}
        # Opcional: filtrar por "updated_since" ISO string en el futuro
        # updated_since = data.get("updated_since")

        Person = request.env['access_control.person'].sudo()
        persons = Person.search([('active', '=', True)], order='id asc')

        users = []
        for p in persons:
            users.append({
                "userId": p.id,          # <- numérico, perfecto para F18 enrollNumber
                "name": p.name,
                "pin": p.pin or "",
            })

        return {"ok": True, "reason": "ok", "users": users}
