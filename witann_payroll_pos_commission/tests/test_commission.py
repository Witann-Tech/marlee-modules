from datetime import date
import importlib.util
import json
from pathlib import Path
from lxml import etree
from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged, new_test_user
from odoo.tools import mute_logger
from odoo.addons.l10n_mx_edi.tests.common import TestMxEdiCommon


@tagged('post_install', '-at_install')
class TestPosPayrollCommission(TestMxEdiCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('hr_payroll.group_hr_payroll_manager')
        cls.env.user.group_ids |= cls.env.ref('point_of_sale.group_pos_manager')
        cls.company.resource_calendar_id.tz = 'America/Mexico_City'
        cls.company.partner_id.zip = '20000'
        cls.company.l10n_mx_imss_id = 'B5510768108'
        cls.company.vat = 'URE180429TM6'
        cls.seller = new_test_user(
            cls.env, login='commission_seller', groups='base.group_user,point_of_sale.group_pos_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)],
        )
        cls.other_seller = new_test_user(
            cls.env, login='commission_other_seller', groups='base.group_user,point_of_sale.group_pos_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)],
        )
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Vendedor POS', 'company_id': cls.company.id, 'user_id': cls.seller.id,
            'date_version': '2024-01-01', 'contract_date_start': '2024-01-01',
            'wage': 30000, 'schedule_pay': 'bi-weekly',
            'structure_type_id': cls.env.ref('l10n_mx_hr_payroll.l10n_mx_employee').id,
            'witann_pos_commission_rate': 1,
            'l10n_mx_rfc': 'XOJI740919U48', 'registration_number': '120',
            'ssnid': '000000', 'l10n_mx_curp': 'XEXX010101HNEXXXA4', 'private_zip': '76028',
            'l10n_mx_regime_type': '03',
            'contract_type_id': cls.env.ref('l10n_mx_hr_payroll_account_edi.l10n_mx_contract_type_01').id,
        })
        cls.structure = cls.env.ref('l10n_mx_hr_payroll.l10n_mx_regular_pay')
        cls.structure.journal_id = cls.env['account.journal'].create({
            'name': 'Nómina comisiones', 'code': 'NOMCP', 'type': 'general',
            'company_id': cls.company.id,
            'default_account_id': cls.company_data['default_account_expense'].id,
        })
        cls.config = cls.env['pos.config'].create({'name': 'POS comisiones', 'company_id': cls.company.id})
        cls.session = cls.env['pos.session'].create({'config_id': cls.config.id, 'user_id': cls.seller.id})

    def order(self, base=100000, tax=16000, when='2026-09-10 12:00:00', user=None, state='paid', employee=None):
        return self.env['pos.order'].create({
            'session_id': self.session.id, 'company_id': self.company.id,
            'user_id': (user or self.seller).id, 'date_order': when,
            'employee_id': employee.id if employee else False,
            'amount_total': base + tax, 'amount_tax': tax,
            'amount_paid': base + tax, 'amount_return': 0, 'state': state,
        })

    def slip(self, first='2026-10-01', last='2026-10-15', employee=None):
        return self.env['hr.payslip'].create({
            'name': 'Comisión de prueba', 'employee_id': (employee or self.employee).id,
            'struct_id': self.structure.id, 'date_from': first, 'date_to': last,
        })

    def line(self, slip):
        return slip.line_ids.filtered(lambda l: l.code == 'COMMISSIONS')

    def foreign_source(self):
        branch = self.setup_other_company(name='Sucursal POS')['company']
        self.env.user.company_ids |= branch
        origin_env = self.env['hr.employee'].with_company(branch).env
        cashier = origin_env['hr.employee'].create({'name': 'Cajera sucursal', 'company_id': branch.id})
        config = origin_env['pos.config'].create({
            'name': 'POS sucursal', 'company_id': branch.id, 'module_pos_hr': True,
            'basic_employee_ids': [Command.set(cashier.ids)],
        })
        session = origin_env['pos.session'].create({'config_id': config.id, 'user_id': self.env.user.id})
        self.employee.with_context(allowed_company_ids=[self.company.id, branch.id]).write({
            'user_id': False, 'witann_pos_source_config_id': config.id,
            'witann_pos_source_employee_id': cashier.id,
        })
        return cashier, config, session

    def source_order(self, cashier, session, base=100000, tax=16000, **overrides):
        return self.env['pos.order'].with_company(session.company_id).create({
            'session_id': session.id, 'company_id': session.company_id.id,
            'employee_id': cashier.id, 'user_id': self.env.user.id,
            'date_order': '2026-09-10 12:00:00', 'amount_total': base + tax,
            'amount_tax': tax, 'amount_paid': base + tax, 'amount_return': 0,
            'state': 'paid', **overrides,
        })

    def payroll_employee(self, **values):
        return self.env['hr.employee'].create({
            'name': 'Otra ficha de nómina', 'company_id': self.company.id,
            'date_version': '2024-01-01', 'contract_date_start': '2024-01-01',
            'wage': 30000, 'schedule_pay': 'bi-weekly',
            'structure_type_id': self.employee.structure_type_id.id, **values,
        })

    def test_mapped_source_two_fortnights_and_native_cfdi(self):
        cashier, config, session = self.foreign_source()
        self.source_order(cashier, session)
        # Reuse the full native payroll, accounting and rendered CFDI assertions.
        # Its local-company order must be ignored by the explicit source.
        self.test_two_fortnights_native_rule_and_cfdi()
        self.assertEqual(self.employee.company_id, self.company)
        self.assertEqual(cashier.company_id, config.company_id)
        self.assertEqual(config.basic_employee_ids, cashier)

    def test_mapped_source_filters_pos_cashier_and_month_without_pos_rights(self):
        cashier, config, session = self.foreign_source()
        order = self.source_order(cashier, session)
        self.source_order(cashier, session, -10000, -1600)
        self.source_order(cashier, session, state='draft')
        self.source_order(cashier, session, date_order='2026-10-02 12:00:00')
        self.source_order(cashier, session, employee_id=False)
        other = cashier.env['hr.employee'].create({'name': 'Otra cajera', 'company_id': config.company_id.id})
        self.source_order(other, session)
        another_config = config.copy({'name': 'Otro POS'})
        another_session = session.env['pos.session'].create({'config_id': another_config.id})
        self.source_order(cashier, another_session)
        officer = new_test_user(
            self.env, login='mapped_payroll_officer', groups='base.group_user,hr_payroll.group_hr_payroll_user',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)],
        )
        slip = self.slip().with_user(officer).with_context(allowed_company_ids=self.company.ids)
        slip.compute_sheet()
        self.assertEqual(slip.company_id, self.company)
        self.assertEqual(slip.witann_pos_base, 90000)
        self.assertEqual(slip.witann_pos_amount, 450)
        self.assertEqual(slip.witann_pos_order_count, 2)
        self.assertEqual(slip.witann_pos_source_config_id.id, config.id)
        self.assertEqual(slip.witann_pos_source_employee_id.id, cashier.id)
        self.assertEqual(slip.witann_pos_evidence[0]['order_id'], order.id)
        self.assertEqual(slip.witann_pos_evidence[0]['config_id'], config.id)
        self.assertFalse(officer.has_group('point_of_sale.group_pos_user'))
        # The origin is reviewable on the receipt without granting POS access.
        displayed = slip.read(['witann_pos_source_config_id', 'witann_pos_source_employee_id'])[0]
        self.assertEqual(displayed['witann_pos_source_config_id'][0], config.id)
        with self.assertRaises(AccessError):
            self.env['witann.pos.commission.claim'].with_user(officer).search([])
        self.employee.witann_pos_commission_rate = 0
        slip.compute_sheet()
        self.assertFalse(self.line(slip))
        self.assertFalse(self.env['witann.pos.commission.claim'].sudo().search([('payslip_id', '=', slip.id)]))

    def test_mapped_source_requires_manager_and_access_to_source(self):
        cashier, config, session = self.foreign_source()
        for groups in ('hr_payroll.group_hr_payroll_user',
                       'hr_payroll.group_hr_payroll_manager,point_of_sale.group_pos_manager'):
            with self.subTest(groups=groups):
                officer = new_test_user(
                    self.env, login='limited_' + groups.split(',')[0], groups='base.group_user,' + groups,
                    company_id=self.company.id, company_ids=[Command.set(self.company.ids)],
                )
                with self.assertRaises(AccessError), self.cr.savepoint():
                    self.employee.with_user(officer).write({
                        'witann_pos_source_config_id': config.id,
                        'witann_pos_source_employee_id': cashier.id,
                    })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.employee.write({'witann_pos_source_employee_id': self.employee.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.employee.write({'witann_pos_source_config_id': False})

    def test_mapped_source_revocation_and_no_implicit_fallback(self):
        cashier, config, session = self.foreign_source()
        self.source_order(cashier, session)
        self.order()  # Must not become a fallback after source access is revoked.
        slip = self.slip()
        slip.compute_sheet()
        config.module_pos_hr = False
        self.assertFalse(self.employee.witann_pos_commission_eligible)
        slip.compute_sheet()
        self.assertFalse(self.line(slip))

    def test_mapped_source_frozen_with_validated_month(self):
        cashier, config, session = self.foreign_source()
        self.source_order(cashier, session)
        first = self.slip()
        first.compute_sheet()
        first.action_payslip_done()
        another = cashier.env['hr.employee'].create({'name': 'Otro origen', 'company_id': config.company_id.id})
        config.write({'basic_employee_ids': [Command.link(another.id)]})
        self.source_order(another, session, 300000, 48000)
        self.employee.with_context(allowed_company_ids=[self.company.id, config.company_id.id]).write({
            'witann_pos_source_employee_id': another.id, 'witann_pos_commission_rate': 2,
        })
        second = self.slip('2026-10-16', '2026-10-31')
        second.compute_sheet()
        self.assertEqual(second.witann_pos_amount, 500)
        self.assertEqual(second.witann_pos_source_employee_id.id, cashier.id)

    def test_mapped_source_duplicate_payroll_employees_and_sql_guard(self):
        cashier, config, session = self.foreign_source()
        self.source_order(cashier, session)
        other = self.payroll_employee()
        other.with_context(allowed_company_ids=[self.company.id, config.company_id.id]).write({
            'witann_pos_source_config_id': config.id, 'witann_pos_source_employee_id': cashier.id,
            'witann_pos_commission_rate': 1,
        })
        first, duplicate = self.slip(), self.slip(employee=other)
        first.compute_sheet()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            duplicate.compute_sheet()
        claim = self.env['witann.pos.commission.claim'].sudo().search([('payslip_id', '=', first.id)])
        with self.assertRaises(IntegrityError), self.cr.savepoint(), mute_logger('odoo.sql_db'):
            self.cr.execute('INSERT INTO witann_pos_commission_claim (payslip_id, config_id, seller_key, period) VALUES (%s,%s,%s,%s)',
                            [duplicate.id, config.id, claim.seller_key, first.witann_pos_period])
        first.action_payslip_cancel()
        duplicate.compute_sheet()
        self.assertEqual(duplicate.witann_pos_amount, 500)

    def test_direct_and_mapped_source_cannot_pay_twice(self):
        self.config.write({'module_pos_hr': True, 'basic_employee_ids': [Command.set(self.employee.ids)]})
        self.order(employee=self.employee)
        other = self.payroll_employee(
            witann_pos_source_config_id=self.config.id, witann_pos_source_employee_id=self.employee.id,
            witann_pos_commission_rate=1,
        )
        direct, mapped = self.slip(), self.slip(employee=other)
        direct.compute_sheet()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            mapped.compute_sheet()
        direct.action_payslip_cancel()
        mapped.compute_sheet()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.slip().compute_sheet()

    def test_upgrade_reserves_historical_origins_idempotently(self):
        self.order()
        slip = self.slip()
        slip.compute_sheet()
        self.env['witann.pos.commission.claim'].sudo().search([('payslip_id', '=', slip.id)]).unlink()
        old_evidence = [{key: value for key, value in item.items()
                         if key not in ('config_id', 'config_name', 'company_id', 'company_name', 'employee_id', 'user_id')}
                        for item in slip.witann_pos_evidence]
        self.cr.execute('UPDATE hr_payslip SET witann_pos_evidence = %s, witann_pos_source_employee_id = NULL WHERE id = %s',
                        [json.dumps(old_evidence), slip.id])
        slip.invalidate_recordset()
        path = Path(__file__).parents[1] / 'migrations/19.0.1.2.0/post-migrate.py'
        spec = importlib.util.spec_from_file_location('commission_migration_test', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.migrate(self.cr, '19.0.1.1.0')
        migration.migrate(self.cr, '19.0.1.1.0')
        claims = self.env['witann.pos.commission.claim'].sudo().search([('payslip_id', '=', slip.id)])
        self.assertEqual(set(claims.mapped('seller_key')), {'employee:%s' % self.employee.id, 'user:%s' % self.seller.id})
        self.assertEqual(slip.witann_pos_evidence, old_evidence)

    def test_two_fortnights_native_rule_and_cfdi(self):
        self.order()
        first = self.slip()
        second = self.slip('2026-10-16', '2026-10-31')
        (first | second).compute_sheet()
        for slip in first | second:
            self.assertEqual(slip.witann_pos_base, 100000)
            self.assertEqual(slip.witann_pos_amount, 500)
            self.assertEqual(self.line(slip).total, 500)
            self.assertEqual(self.line(slip).name, 'Comisión por venta')
            self.assertEqual(self.line(slip).salary_rule_id.l10n_mx_concept.sat_code, '028')
            slip.action_payslip_done()
            slip.move_id.action_post()
            slip.paid_date = slip.date_to
            document = self.env['l10n_mx_edi.document']
            with self.mx_external_setup(self.frozen_today):
                self.company.l10n_mx_edi_certificate_ids = self.certificate
                cfdi = document._get_company_cfdi_values(self.company)
                document._add_certificate_cfdi_values(cfdi)
                cfdi = slip._l10n_mx_edi_add_payslip_cfdi_values(cfdi)
            self.assertFalse(cfdi.get('errors'), cfdi.get('errors'))
            commissions = [p for p in cfdi['percepcion_list'] if p['tipo_percepcion'] == '028']
            self.assertEqual(len(commissions), 1)
            self.assertEqual(commissions[0]['importe_gravado'], 500)
            self.assertEqual(commissions[0]['concepto'], 'Comisión por venta')
            document._clean_cfdi_values(cfdi)
            xml = self.env['ir.qweb']._render('l10n_mx_hr_payroll_account_edi.cfdiv40_nomina', cfdi)
            root = etree.fromstring(xml.encode())
            perception = root.xpath('//*[local-name()="Percepcion"][@TipoPercepcion="028"]')
            self.assertEqual(len(perception), 1)
            self.assertEqual(perception[0].get('ImporteGravado'), '500.00')
            self.assertEqual(perception[0].get('Concepto'), 'Comisión por venta')
        self.assertEqual(first.witann_pos_amount + second.witann_pos_amount, 1000)

    def test_filters_and_refunds_without_tax(self):
        self.order()
        self.order(-10000, -1600)
        self.order(user=self.other_seller)
        self.order(state='draft')
        self.order(state='cancel')
        self.order(when='2026-08-31 12:00:00')
        self.order(when='2026-10-01 12:00:00')
        slip = self.slip()
        slip.compute_sheet()
        self.assertEqual(slip.witann_pos_base, 90000)
        self.assertEqual(slip.witann_pos_amount, 450)
        self.assertEqual(slip.witann_pos_order_count, 2)

    def test_timezone_half_open_boundaries(self):
        self.order(100, 16, when='2026-09-01 05:59:59')
        self.order(200, 32, when='2026-09-01 06:00:00')
        self.order(300, 48, when='2026-10-01 05:59:59')
        self.order(400, 64, when='2026-10-01 06:00:00')
        slip = self.slip()
        slip.compute_sheet()
        self.assertEqual(slip.witann_pos_base, 500)
        self.assertEqual(slip.witann_pos_amount, 2.5)

    def test_recompute_and_disable(self):
        self.order()
        slip = self.slip()
        slip.compute_sheet()
        slip.compute_sheet()
        self.assertEqual(len(slip.input_line_ids.filtered('witann_pos_commission')), 1)
        self.assertEqual(len(self.line(slip)), 1)
        self.employee.witann_pos_commission_rate = 2
        slip.compute_sheet()
        self.assertEqual(self.line(slip).total, 1000)
        self.employee.witann_pos_commission_rate = 0
        slip.compute_sheet()
        self.assertFalse(self.line(slip))
        self.assertFalse(slip.input_line_ids.filtered('witann_pos_commission'))
        self.assertFalse(slip.witann_pos_month)

    def test_no_sales_or_negative_base_no_income(self):
        slip = self.slip()
        slip.compute_sheet()
        self.assertFalse(self.line(slip))
        self.order(-1000, -160)
        slip.compute_sheet()
        self.assertEqual(slip.witann_pos_base, -1000)
        self.assertFalse(self.line(slip))

    def test_zero_is_default_and_non_pos_not_eligible(self):
        employee = self.env['hr.employee'].create({'name': 'Sin POS'})
        self.assertFalse(employee.witann_pos_commission_eligible)
        self.assertEqual(employee.witann_pos_commission_rate, 0)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            employee.witann_pos_commission_rate = 1

    def test_invalid_rates(self):
        for value in (-1, 100.01):
            with self.subTest(value=value), self.assertRaises(ValidationError), self.cr.savepoint():
                self.employee.witann_pos_commission_rate = value

    def test_cashiers_without_users_share_session_but_not_sales(self):
        self.employee.write({'witann_pos_commission_rate': 0, 'user_id': False})
        second = self.env['hr.employee'].create({
            'name': 'Segunda cajera', 'company_id': self.company.id,
            'date_version': '2024-01-01', 'contract_date_start': '2024-01-01',
            'wage': 30000, 'schedule_pay': 'bi-weekly',
            'structure_type_id': self.employee.structure_type_id.id,
        })
        self.assertFalse(self.employee.witann_pos_commission_eligible)
        self.config.write({
            'module_pos_hr': True,
            'basic_employee_ids': [Command.set((self.employee | second).ids)],
        })
        self.assertTrue(self.employee.witann_pos_commission_eligible)
        self.assertTrue(second.witann_pos_commission_eligible)
        self.employee.witann_pos_commission_rate = 1
        second.witann_pos_commission_rate = 2
        self.order(employee=self.employee)
        self.order(-10000, -1600, employee=self.employee)
        self.order(50000, 8000, employee=second)
        self.order()  # Session user's unassigned ticket belongs to neither cashier.
        officer = new_test_user(
            self.env, login='cashier_payroll_officer',
            groups='base.group_user,hr_payroll.group_hr_payroll_user',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)],
        )
        first_slip = self.slip().with_user(officer)
        second_slip = self.slip(employee=second).with_user(officer)
        (first_slip | second_slip).compute_sheet()
        self.assertEqual(first_slip.witann_pos_base, 90000)
        self.assertEqual(self.line(first_slip).total, 450)
        self.assertEqual(second_slip.witann_pos_base, 50000)
        self.assertEqual(self.line(second_slip).total, 500)
        self.assertFalse(first_slip.witann_pos_user_id)

    def test_cashier_takes_precedence_over_session_user(self):
        other = self.env['hr.employee'].create({'name': 'Otra cajera', 'company_id': self.company.id})
        self.order(1000, 160)  # Legacy user-attributed sale.
        self.order(2000, 320, employee=self.employee, user=self.other_seller)
        self.order(5000, 800, employee=other)  # Our user opened POS, another cashier sold.
        slip = self.slip()
        slip.compute_sheet()
        self.assertEqual(slip.witann_pos_base, 3000)
        self.assertEqual(slip.witann_pos_order_count, 2)

    def test_cashier_access_levels_and_revocation(self):
        cashier = self.env['hr.employee'].create({'name': 'Cajera', 'company_id': self.company.id})
        excluded = self.env['hr.employee'].create({'name': 'Sin acceso', 'company_id': self.company.id})
        self.config.write({'module_pos_hr': True, 'basic_employee_ids': [Command.set(self.employee.ids)]})
        self.assertFalse(cashier.witann_pos_commission_eligible)
        for field in ('minimal_employee_ids', 'basic_employee_ids', 'advanced_employee_ids'):
            with self.subTest(field=field):
                self.config.write({field: [Command.link(cashier.id)]})
                self.assertTrue(cashier.witann_pos_commission_eligible)
                self.assertFalse(excluded.witann_pos_commission_eligible)
                self.config.write({field: [Command.unlink(cashier.id)]})
                self.assertFalse(cashier.witann_pos_commission_eligible)

    def test_open_cashier_access_requires_active_enabled_pos(self):
        cashier = self.env['hr.employee'].create({'name': 'Cajera', 'company_id': self.company.id})
        self.config.write({'module_pos_hr': True})
        self.assertTrue(cashier.witann_pos_commission_eligible)
        self.config.module_pos_hr = False
        self.assertFalse(cashier.witann_pos_commission_eligible)
        self.config.module_pos_hr = True
        self.session.state = 'closed'
        self.config.active = False
        self.assertFalse(cashier.witann_pos_commission_eligible)
        self.config.active = True
        self.assertTrue(cashier.witann_pos_commission_eligible)
        cashier.active = False
        self.assertFalse(cashier.witann_pos_commission_eligible)

    def test_cashier_access_does_not_cross_companies(self):
        other_company = self.setup_other_company(name='Otra compañía cajeros')['company']
        cashier = self.env['hr.employee'].sudo().create({
            'name': 'Cajera otra compañía', 'company_id': other_company.id,
        })
        self.config.write({'module_pos_hr': True})
        self.assertFalse(cashier.witann_pos_commission_eligible)

    def test_revoked_pos_access_stops_commission(self):
        self.order()
        slip = self.slip()
        slip.compute_sheet()
        self.seller.group_ids -= self.env.ref('point_of_sale.group_pos_user')
        self.assertFalse(self.employee.witann_pos_commission_eligible)
        slip.compute_sheet()
        self.assertFalse(self.line(slip))

    def test_non_quincenal_and_partial_period_rejected(self):
        slip = self.slip('2026-10-02', '2026-10-15')
        with self.assertRaises(UserError), self.cr.savepoint():
            slip.compute_sheet()
        self.employee.schedule_pay = 'monthly'
        with self.assertRaises(UserError), self.cr.savepoint():
            self.slip().compute_sheet()

    def test_manual_commissions_preserved_and_conflict_reported(self):
        self.order()
        slip = self.slip()
        manual = self.env['hr.payslip.input'].create({
            'payslip_id': slip.id, 'name': 'Comisión manual', 'amount': 50,
            'input_type_id': self.env.ref('l10n_mx_hr_payroll.l10n_mx_input_commissions').id,
        })
        with self.assertRaises(UserError), self.cr.savepoint():
            slip.compute_sheet()
        self.assertEqual(manual.amount, 50)
        self.employee.witann_pos_commission_rate = 0
        slip.compute_sheet()
        self.assertEqual(self.line(slip).total, 50)

    def test_duplicate_fortnight_rejected_and_cancel_releases(self):
        self.order()
        first, duplicate = self.slip(), self.slip()
        first.compute_sheet()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            duplicate.compute_sheet()
            self.env.flush_all()
        first.action_payslip_cancel()
        duplicate.compute_sheet()
        self.assertEqual(self.line(duplicate).total, 500)

    def test_managed_input_and_snapshot_cannot_be_forged(self):
        self.order()
        slip = self.slip()
        slip.compute_sheet()
        managed = slip.input_line_ids.filtered('witann_pos_commission')
        with self.assertRaises(ValidationError):
            managed.write({'amount': 999})
        with self.assertRaises(ValidationError):
            managed.unlink()
        with self.assertRaises(ValidationError):
            slip.write({'witann_pos_amount': 999})

    def test_database_index_catches_bypass_of_duplicate_precheck(self):
        self.order()
        first, second = self.slip(), self.slip('2026-10-16', '2026-10-31')
        (first | second).compute_sheet()
        self.env.flush_all()
        with self.assertRaises(IntegrityError), self.cr.savepoint(), mute_logger('odoo.sql_db'):
            self.cr.execute('UPDATE hr_payslip SET witann_pos_period = %s WHERE id = %s',
                            [first.witann_pos_period, second.id])

    def test_refund_preserves_native_negative_lines_without_new_commission(self):
        self.order()
        slip = self.slip()
        slip.compute_sheet()
        slip.action_payslip_done()
        refund = slip._action_refund_payslips()
        self.assertEqual(self.line(refund).total, -500)
        self.assertFalse(refund.witann_pos_period)
        with self.assertRaises(UserError), self.cr.savepoint():
            refund.compute_sheet()

    def test_other_company_sales_excluded(self):
        self.order()
        other_company = self.setup_other_company(name='Otra compañía POS')['company']
        self.env.user.company_ids |= other_company
        other_config = self.env['pos.config'].with_company(other_company).create({
            'name': 'POS otra compañía', 'company_id': other_company.id})
        other_session = self.env['pos.session'].with_company(other_company).create({
            'config_id': other_config.id, 'user_id': self.env.user.id})
        self.env['pos.order'].sudo().create({
            'session_id': other_session.id, 'company_id': other_company.id,
            'user_id': self.seller.id, 'date_order': '2026-09-10 12:00:00',
            'amount_total': 232000, 'amount_tax': 32000,
            'amount_paid': 232000, 'amount_return': 0, 'state': 'paid',
        })
        slip = self.slip()
        slip.compute_sheet()
        self.assertEqual(slip.witann_pos_base, 100000)

    def test_extraordinary_structure_has_no_automatic_commission(self):
        self.order()
        slip = self.slip()
        slip.struct_id = self.structure.copy({'name': 'Extraordinaria de prueba'})
        slip.compute_sheet()
        self.assertFalse(slip.witann_pos_month)
        self.assertFalse(self.line(slip))

    def test_payroll_officer_without_pos_can_compute(self):
        self.order()
        officer = new_test_user(
            self.env, login='commission_officer', groups='base.group_user,hr_payroll.group_hr_payroll_user',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)],
        )
        self.assertFalse(officer.has_group('point_of_sale.group_pos_user'))
        slip = self.slip().with_user(officer)
        slip.compute_sheet()
        self.assertEqual(slip.witann_pos_amount, 500)
        with self.assertRaises(AccessError):
            self.employee.with_user(self.seller).write({'witann_pos_commission_rate': 5})

    def test_month_frozen_after_validation_and_historical_receipt_unchanged(self):
        self.order()
        first = self.slip()
        first.compute_sheet()
        first.action_payslip_done()
        self.order()
        self.employee.witann_pos_commission_rate = 2
        first.compute_sheet()
        self.assertEqual(first.witann_pos_amount, 500)
        second = self.slip('2026-10-16', '2026-10-31')
        second.compute_sheet()
        self.assertEqual(second.witann_pos_amount, 500)
        self.assertEqual(second.witann_pos_base, 100000)
        with self.assertRaises(ValidationError):
            first.write({'date_from': date(2026, 10, 2)})

    def test_amount_enters_taxable_and_net(self):
        self.order()
        slip = self.slip()
        self.employee.witann_pos_commission_rate = 0
        slip.compute_sheet()
        gross_before = sum(slip.line_ids.filtered(lambda l: l.code == 'GROSS').mapped('total'))
        net_before = slip.net_wage
        self.employee.witann_pos_commission_rate = 1
        slip.compute_sheet()
        gross_after = sum(slip.line_ids.filtered(lambda l: l.code == 'GROSS').mapped('total'))
        self.assertAlmostEqual(gross_after - gross_before, 500)
        self.assertGreater(slip.net_wage, net_before)
        self.assertLess(slip.net_wage - net_before, 500)
