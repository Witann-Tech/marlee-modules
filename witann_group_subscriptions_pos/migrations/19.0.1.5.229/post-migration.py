from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    imd = env['ir.model.data'].sudo().search([
        ('module', '=', 'witann_group_subscriptions_pos'),
        ('name', '=', 'ir_cron_wgs_close_overdue_subscriptions'),
    ], limit=1)
    legacy = env.ref(
        'witann_group_subscriptions_pos.ir_cron_wgs_close_overdue_subscriptions',
        raise_if_not_found=False,
    )
    if legacy:
        legacy.active = False
        legacy.unlink()
    if imd:
        imd.unlink()
