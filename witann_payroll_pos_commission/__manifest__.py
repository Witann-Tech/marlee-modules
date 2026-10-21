{
    'name': 'Witann: comisión POS en nómina',
    'version': '19.0.1.2.0',
    'summary': 'Comisión mensual por cajero o usuario POS, pagada en dos quincenas',
    'description': 'Añade a la nómina mexicana nativa una comisión configurable por empleado sobre las ventas POS sin impuestos del mes anterior, pagada en dos quincenas e integrada en el CFDI.',
    'category': 'Human Resources/Payroll',
    'author': 'Witann Technologies',
    'license': 'LGPL-3',
    'depends': ['pos_hr', 'l10n_mx_hr_payroll_account_edi'],
    'data': ['views/hr_employee_views.xml', 'views/hr_payslip_views.xml'],
    'installable': True,
    'application': False,
}
