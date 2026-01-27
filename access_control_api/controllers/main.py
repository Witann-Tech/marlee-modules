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
        data = request.jsonrequest or payload or {}
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
