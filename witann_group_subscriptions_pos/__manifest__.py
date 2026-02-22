{
    'name': 'Witann Group Subscriptions POS',
    'version': '19.0.1.4.8',
    'summary': 'Consulta de vigencia de paquetes de suscripción en Punto de Venta',
    'category': 'Point of Sale',
    'author': 'Witann Technologies',
    'license': 'LGPL-3',
    'depends': [
        'point_of_sale',
        'sale_subscription',
        'witann_group_subscriptions',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'witann_group_subscriptions_pos/static/src/js/subscription_status_button.js',
            'witann_group_subscriptions_pos/static/src/xml/subscription_status_button.xml',
        ],
    },
    'installable': True,
    'application': False,
}
