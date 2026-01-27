# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class AccessControlApi(http.Controller):

    @http.route('/api/access/validate', type='json', auth='public', methods=['POST'], csrf=False)
    def validate(self, **payload):
        # Respuesta dummy (por ahora)
        return {
            "allowed": False,
            "reason": "endpoint_alive",
            "openMs": 500
        }

