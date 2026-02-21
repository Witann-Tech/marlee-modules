from odoo import fields, models


class WgsPosSubscriptionBuffer(models.Model):
    _name = 'wgs.pos.subscription.buffer'
    _description = 'WGS POS Subscription Config Buffer'

    order_uuid = fields.Char(string='UUID de Orden POS', required=True, index=True)
    payload_json = fields.Text(string='Payload JSON', required=True)
