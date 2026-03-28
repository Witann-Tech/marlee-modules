{
    'name': 'Witann Group Subscriptions',
    'version': '19.0.1.0.36',
    'summary': 'Participantes permitidos en suscripciones de gimnasio',
    'category': 'Sales/Subscriptions',
    'author': 'Witann Technologies',
    'license': 'LGPL-3',
    'depends': ['sale_subscription', 'access_control_api'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/sale_order_views.xml',
        'views/subscription_import_wizard_views.xml',
    ],
    'installable': True,
    'application': True,
}
