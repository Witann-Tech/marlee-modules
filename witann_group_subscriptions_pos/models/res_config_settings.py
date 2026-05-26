from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    wgs_authorization_pin_rotation_days = fields.Integer(
        string='Rotar PIN de autorización cada',
        default=30,
        config_parameter='wgs_subscriptions_pos.authorization_pin_rotation_days',
        help='Número de días para regenerar automáticamente el PIN de autorización WGS. Usa 0 para desactivar la rotación automática.',
    )
