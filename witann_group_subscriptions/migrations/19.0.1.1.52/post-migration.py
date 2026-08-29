import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


_OBSOLETE_IMPORT_XMLIDS = (
    'wgs_subscription_import_wizard_form',
    'action_wgs_subscription_import_wizard',
    'access_wgs_subscription_import_wizard_manager',
    'access_wgs_subscription_import_line_manager',
)


def migrate(cr, version):
    """Remove UI metadata for the retired subscription import wizard."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    data_records = env['ir.model.data'].sudo().search([
        ('module', '=', 'witann_group_subscriptions'),
        ('name', 'in', _OBSOLETE_IMPORT_XMLIDS),
    ])
    removed = 0
    for data_record in data_records:
        model = env[data_record.model] if data_record.model in env.registry else False
        record = model.browse(data_record.res_id).exists() if model else False
        if record:
            record.unlink()
        data_record.unlink()
        removed += 1
    _logger.info('WGS subscriptions: removed %s obsolete import wizard metadata record(s).', removed)
