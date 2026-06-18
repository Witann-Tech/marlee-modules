from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    xmlid = 'witann_group_subscriptions_pos.ir_cron_wgs_close_overdue_subscriptions'
    legacy_cron = env.ref(xmlid, raise_if_not_found=False)
    if legacy_cron:
        legacy_cron.active = False
        legacy_cron.unlink()

    module, name = xmlid.split('.', 1)
    env['ir.model.data'].sudo().search([
        ('module', '=', module),
        ('name', '=', name),
    ]).unlink()
