{
    'name': 'Witann POS Early Receipt',
    'version': '19.0.1.0.1',
    'summary': 'Imprime una precuenta antes del pago en POS no restaurante',
    'category': 'Point of Sale',
    'author': 'Witann Technologies',
    'license': 'LGPL-3',
    'depends': ['point_of_sale'],
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'witann_pos_early_receipt/static/src/js/early_receipt_button.js',
            'witann_pos_early_receipt/static/src/xml/early_receipt_button.xml',
        ],
    },
    'installable': True,
    'application': False,
}
