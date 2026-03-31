{
    'name': 'Witann Group Subscriptions POS',
    'version': '19.0.1.5.55',
    'summary': 'Directorio y detalle de suscripciones nativas en Punto de Venta',
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
            'witann_group_subscriptions_pos/static/src/js/subscription_form_defaults.js',
            'witann_group_subscriptions_pos/static/src/js/subscription_pos_api.js',
            'witann_group_subscriptions_pos/static/src/js/subscription_ticket.js',
            'witann_group_subscriptions_pos/static/src/js/subscription_view_utils.js',
            'witann_group_subscriptions_pos/static/src/js/subscription_status_button.js',
            'witann_group_subscriptions_pos/static/src/xml/subscription_status_button.xml',
        ],
    },
    'installable': True,
    'application': False,
}
