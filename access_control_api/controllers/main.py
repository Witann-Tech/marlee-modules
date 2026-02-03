# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request


class AccessControlApi(http.Controller):

    def _auth_ok(self):
        auth = request.httprequest.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return False, 'missing_token'
        token = auth.split(' ', 1)[1].strip()
        expected = request.env['ir.config_parameter'].sudo().get_param('access_control.api_token')
        if not expected:
            return False, 'server_token_not_configured'
        if token != expected:
            return False, 'invalid_token'
        return True, None


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
                "pin": (p.credential_ids.filtered(lambda c: c.credential_type == 'pin' and c.active)[:1].pin_value) or "",
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


    @http.route(
        '/api/access/enroll/next',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def enroll_next(self, **payload):
        ok, reason = self._auth_ok()
        if not ok:
            return {"ok": False, "reason": reason, "request": None}

        data = request.params or payload or {}
        site_code = data.get("siteCode") or data.get("site_code")
        if not site_code:
            return {"ok": False, "reason": "missing_site_code", "request": None}

        Site = request.env["access_control.site"].sudo()
        site = Site.search([("code", "=", site_code)], limit=1)
        if not site:
            return {"ok": False, "reason": "site_not_found", "request": None}

        Req = request.env["access_control.enroll_request"].sudo()
        req = Req.search([("site_id", "=", site.id), ("status", "=", "requested")], limit=1, order="create_date asc")
        if not req:
            return {"ok": True, "reason": "no_pending", "request": None}

        person = req.person_id
        cred = req.credential_id
        return {
            "ok": True,
            "reason": "pending",
            "request": {
                "request_id": req.id,
                "credential_id": cred.id,
                "person_id": person.id if person else None,
                "partner_id": person.partner_id.id if person and person.partner_id else None,
                "site_code": site.code,
                "f18_user_id": person.f18_user_id if person else None,
                "finger_index": cred.finger_index,
                "template_format": cred.template_format,
            }
        }

    @http.route(
        '/api/access/enroll/ack',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def enroll_ack(self, **payload):
        ok, reason = self._auth_ok()
        if not ok:
            return {"ok": False, "reason": reason}

        data = request.params or payload or {}
        request_id = data.get("request_id") or data.get("requestId")
        if not request_id:
            return {"ok": False, "reason": "missing_request_id"}

        Req = request.env["access_control.enroll_request"].sudo()
        req = Req.browse(int(request_id))
        if not req.exists():
            return {"ok": False, "reason": "request_not_found"}

        if req.status == "requested":
            req.status = "enrolling"
            req.credential_id.enroll_status = "enrolling"
        return {"ok": True, "reason": "ack"}

    @http.route(
        '/api/access/enroll/complete',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def enroll_complete(self, **payload):
        ok, reason = self._auth_ok()
        if not ok:
            return {"ok": False, "reason": reason}

        data = request.params or payload or {}
        request_id = data.get("request_id") or data.get("requestId")
        status = data.get("status")
        if not request_id:
            return {"ok": False, "reason": "missing_request_id"}
        if status not in ("active", "error"):
            return {"ok": False, "reason": "invalid_status"}

        Req = request.env["access_control.enroll_request"].sudo()
        req = Req.browse(int(request_id))
        if not req.exists():
            return {"ok": False, "reason": "request_not_found"}

        cred = req.credential_id
        if status == "active":
            template_b64 = data.get("template_b64") or data.get("templateB64")
            template_format = data.get("template_format") or data.get("templateFormat") or cred.template_format
            quality = data.get("quality")
            if not template_b64:
                return {"ok": False, "reason": "missing_template_b64"}

            cred.write({
                "template_b64": template_b64,
                "template_format": template_format,
                "enroll_status": "active",
                "active": True,
            })
            req.write({
                "status": "done",
                "enrolled_at": request.env.cr.now(),
                "quality": quality,
            })
            # Mark site for sync to push template to F18
            if cred.site_id:
                cred.site_id.force_sync = True

            return {"ok": True, "reason": "stored"}
        else:
            error_code = data.get("error_code") or data.get("errorCode")
            error_message = data.get("error_message") or data.get("errorMessage")
            cred.enroll_status = "error"
            req.write({
                "status": "error",
                "error_code": error_code,
                "error_message": error_message,
            })
            return {"ok": True, "reason": "error_saved"}

