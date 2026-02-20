{
    'name': 'Witann Product Approval',
    'version': '19.0.1.0.0',
    'summary': 'Aprobación de altas y cambios de productos',
    'category': 'Sales',
    'author': 'Witann Technologies',
    'license': 'LGPL-3',
    'depends': ['product'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/product_template_change_request_views.xml',
    ],
    'installable': True,
    'application': False,
}
