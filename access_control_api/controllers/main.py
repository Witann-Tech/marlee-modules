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
            return {"ok": False, "reason": "missing_token", "users": [], "devices": [], "siteCode": None}

        token = auth.split(' ', 1)[1].strip()

        expected = request.env['ir.config_parameter'].sudo().get_param('access_control.api_token')
        if not expected:
            return {"ok": False, "reason": "server_token_not_configured", "users": [], "devices": [], "siteCode": None}

        if token != expected:
            return {"ok": False, "reason": "invalid_token", "users": [], "devices": [], "siteCode": None}

        # ---- Payload / Params ----
        # En type="json", Odoo normalmente recibe JSON-RPC y params vienen en request.jsonrequest["params"].
        # Pero dejamos compatibilidad con request.params/payload.
        data = request.params or payload or {}
        try:
            rpc_params = (request.jsonrequest or {}).get("params") or {}
            if isinstance(rpc_params, dict):
                data = {**data, **rpc_params}
        except Exception:
            pass

        site_code = (data.get("site_code") or "").strip()

        # ---- Users ----
        Person = request.env['access_control.person'].sudo()
        persons = Person.search([('active', '=', True)], order='id asc')

        users = []
        for p in persons:
            users.append({
                "userId": p.id,          # <- numérico, perfecto para F18 enrollNumber
                "name": p.name,
                "pin": p.pin or "",
            })

        # ---- Devices (si viene site_code) ----
        devices = []
        if site_code:
            Site = request.env['access_control.site'].sudo()
            site = Site.search([('code', '=', site_code), ('active', '=', True)], limit=1)
            if not site:
                return {
                    "ok": False,
                    "reason": "site_not_found",
                    "siteCode": site_code,
                    "devices": [],
                    "users": users
                }

            Device = request.env['access_control.device'].sudo()
            devs = Device.search([('site_id', '=', site.id), ('active', '=', True)], order='id asc')

            for d in devs:
                devices.append({
                    "deviceCode": d.device_code,
                    "ip": d.ip,
                    "port": d.port,
                    "commPassword": d.comm_password,
                    "machineNumber": d.machine_number,
                })

        return {
            "ok": True,
            "reason": "ok",
            "siteCode": site_code or None,
            "devices": devices,
            "users": users
        }
