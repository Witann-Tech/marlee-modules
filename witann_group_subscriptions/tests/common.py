"""Deployment-specific contact fields, only on the disposable test database."""


def ensure_partner_identity_fields(env):
    model_id = env['ir.model']._get_id('res.partner')
    for name, kind in (
        ('x_studio_curp', 'char'),
        ('x_studio_fecha_de_nacimiento', 'date'),
    ):
        if name not in env['res.partner']._fields:
            env['ir.model.fields'].sudo().create({
                'name': name, 'field_description': name,
                'model_id': model_id, 'ttype': kind, 'state': 'manual',
            })
