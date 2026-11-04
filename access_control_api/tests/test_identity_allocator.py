from uuid import uuid4
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'wgs_identity')
class TestIdentityAllocator(TransactionCase):
    def test_unauthorized_identity_changes_do_not_acquire_the_allocator(self):
        user = self.env['res.users'].create({
            'name': 'Readonly identity QA', 'login': str(uuid4()),
            'group_ids': [Command.set(self.env.ref('base.group_user').ids)],
        })
        Person = self.env['access_control.person']
        partner = self.env['res.partner'].create({'name': 'ACL identity QA'})
        person = Person.create({'partner_id': partner.id})
        with patch.object(type(Person), '_lock_global_user_id_allocator', autospec=True) as lock:
            with self.assertRaises(AccessError):
                Person.with_user(user).create({'partner_id': partner.id})
            with self.assertRaises(AccessError):
                person.with_user(user).write({'global_user_id': 9999})
            with self.assertRaises(AccessError):
                person.with_user(user).action_assign_global_user_id()
            lock.assert_not_called()

    def test_auto_assigned_ids_are_distinct_and_explicit_writes_use_the_guard(self):
        Person = self.env['access_control.person']
        partners = self.env['res.partner'].create([{'name': 'Identity QA %s' % uuid4()} for _ in range(2)])
        people = Person.create([{'partner_id': partner.id} for partner in partners])
        self.assertEqual(len(set(people.mapped('global_user_id'))), 2)
        self.assertTrue(all(1 <= person.global_user_id <= 10000 for person in people))
        first_id = people[0].global_user_id
        people[0].write({'global_user_id': False})
        people[0].action_assign_global_user_id()
        self.assertEqual(people[0].global_user_id, first_id)

    def test_failed_creation_rolls_back_the_identity_without_committing(self):
        Person = self.env['access_control.person']
        partner = self.env['res.partner'].create({'name': 'Rollback identity QA %s' % uuid4()})
        chosen = False
        with self.assertRaises(UserError), self.env.cr.savepoint():
            person = Person.create({'partner_id': partner.id})
            chosen = person.global_user_id
            raise UserError('Rollback test')
        self.assertFalse(Person.with_context(active_test=False).search([('partner_id', '=', partner.id)]))
        person = Person.create({'partner_id': partner.id})
        self.assertEqual(person.global_user_id, chosen)

    def test_multiple_archived_people_can_release_ids_and_reassign_them(self):
        Person = self.env['access_control.person']
        partners = self.env['res.partner'].create([{'name': 'Archive QA %s' % uuid4()} for _ in range(2)])
        people = Person.create([{'partner_id': partner.id} for partner in partners])
        before = sorted(people.mapped('global_user_id'))
        people.write({'active': False})
        people.flush_recordset(['global_user_id'])
        self.assertFalse(any(people.mapped('global_user_id')))
        people.action_assign_global_user_id()
        people.flush_recordset(['global_user_id'])
        self.assertEqual(sorted(people.mapped('global_user_id')), before)

    def test_active_person_cannot_lose_its_identity(self):
        site = self.env['access_control.site'].create({'name': 'Active ID QA', 'code': str(uuid4())})
        partner = self.env['res.partner'].create({'name': 'Active identity QA'})
        person = self.env['access_control.person'].create({'partner_id': partner.id, 'active': True,
                                                         'site_ids': [(6, 0, site.ids)]})
        previous = person.global_user_id
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            person.write({'global_user_id': False})
        self.assertEqual(person.global_user_id, previous)
