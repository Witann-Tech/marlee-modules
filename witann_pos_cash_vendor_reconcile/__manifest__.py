{
    'name': 'Witann POS Cash Vendor Reconciliation',
    'version': '19.0.1.0.0',
    'summary': 'Concilia salidas de efectivo del POS con facturas de proveedor',
    'description': 'Aplica salidas manuales de caja POS a las deudas de proveedores mediante conciliación contable nativa.',
    'category': 'Accounting/Accounting',
    'author': 'Witann Technologies',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'security/reconciliation_rules.xml',
        'wizard/cash_vendor_reconcile_views.xml',
        'views/cash_out_views.xml',
        'views/pos_session_views.xml',
    ],
    'installable': True,
    'application': False,
}
