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

        # TODO: mover a ir.config_parameter
        expected = "TU_TOKEN_DE_STAGING"

        if token != expected:
            return {"allowed": False, "reason": "invalid_token", "openMs": None}

        return {"allowed": False, "reason": "endpoint_alive", "openMs": 500}
