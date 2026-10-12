{
    'name': 'Witann Bank Import Deduplicate',
    'version': '19.0.1.0.2',
    'summary': 'Importa únicamente movimientos bancarios nuevos desde CSV/XLSX',
    'category': 'Accounting/Accounting',
    'author': 'Witann Technologies',
    'license': 'LGPL-3',
    'depends': ['account'],
    'external_dependencies': {'python': ['openpyxl']},
    'data': [
        'security/ir.model.access.csv',
        'security/bank_import_rules.xml',
        'wizard/bank_import_views.xml',
        'views/account_journal_views.xml',
    ],
    'installable': True,
    'application': False,
}
