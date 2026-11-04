"""Real two-connection Repeatable Read regression for the identity allocator.

Requires WGS_TEST_DSN pointing to a disposable database named wgs_test_*.
Uses only tables in its own random schema, never Odoo business data. This
tests the actual allocator bodies/SQL, not Odoo's full transaction retry loop.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import os
from threading import Event
from types import SimpleNamespace
import unittest
from uuid import uuid4

from test_subscription_contract import method

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    psycopg2 = None


class IdentityAllocatorPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ.get('WGS_TEST_DSN')
        if not cls.dsn or not psycopg2:
            raise unittest.SkipTest('Requires psycopg2 and an explicitly disposable WGS_TEST_DSN')
        cls.schema = 'wgs_allocator_' + uuid4().hex
        with closing(psycopg2.connect(cls.dsn)) as connection:
            if not connection.info.dbname.startswith('wgs_test_'):
                raise RuntimeError('Refusing a database not named wgs_test_*')
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(cls.schema)))
                cursor.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(cls.schema)))
                cursor.execute('CREATE TABLE ir_config_parameter (id integer PRIMARY KEY, value text)')
                cursor.execute("INSERT INTO ir_config_parameter VALUES (1, '1')")
                cursor.execute('CREATE TABLE access_control_person (global_user_id integer UNIQUE)')
            connection.commit()
        cls.lock = staticmethod(method('access_control_api/models/access_person.py', '_lock_global_user_id_allocator'))
        cls.used = staticmethod(method('access_control_api/models/access_person.py', '_used_global_user_ids'))
        cls.next_id = staticmethod(method('access_control_api/models/access_person.py', '_next_available_global_user_id'))

    @classmethod
    def tearDownClass(cls):
        with closing(psycopg2.connect(cls.dsn)) as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(cls.schema)))
            connection.commit()

    @contextmanager
    def session(self):
        with closing(psycopg2.connect(self.dsn)) as connection:
            connection.set_session(isolation_level='REPEATABLE READ')
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(self.schema)))
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL statement_timeout = '10s'")
                env = SimpleNamespace(cr=cursor, ref=lambda xmlid, **kwargs: SimpleNamespace(id=1))
                yield connection, cursor, SimpleNamespace(env=env, flush_model=lambda names: None)
            connection.rollback()

    def setUp(self):
        with self.session() as (connection, cursor, _owner):
            cursor.execute('DELETE FROM access_control_person')
            connection.commit()

    def allocate(self, cursor, owner):
        self.lock(owner)
        chosen = self.next_id(owner, self.used(owner))
        cursor.execute('INSERT INTO access_control_person VALUES (%s)', [chosen])
        return chosen

    def test_overlapping_snapshot_retries_instead_of_colliding_on_unique_id(self):
        snapshot_ready = Event()

        def competing_worker():
            with self.session() as (_connection, cursor, owner):
                self.assertEqual(self.used(owner), set())
                snapshot_ready.set()
                try:
                    self.allocate(cursor, owner)
                except psycopg2.errors.SerializationFailure:
                    return 'fresh_transaction_required'
                self.fail('An overlapping allocator must not continue from its old snapshot')

        # End the first transaction before joining its blocked competitor.
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.session() as (first, cursor, owner):
                self.assertEqual(self.allocate(cursor, owner), 1)
                future = executor.submit(competing_worker)
                self.assertTrue(snapshot_ready.wait(5))
                first.commit()
            self.assertEqual(future.result(timeout=12), 'fresh_transaction_required')
        with self.session() as (connection, cursor, owner):
            self.assertEqual(self.allocate(cursor, owner), 2)
            connection.commit()
        with self.session() as (_connection, cursor, _owner):
            cursor.execute('SELECT global_user_id FROM access_control_person ORDER BY global_user_id')
            self.assertEqual(cursor.fetchall(), [(1,), (2,)])

    def test_rollback_releases_the_identity_and_allocator_lock(self):
        with self.session() as (connection, cursor, owner):
            self.assertEqual(self.allocate(cursor, owner), 1)
            connection.rollback()
        with self.session() as (connection, cursor, owner):
            self.assertEqual(self.allocate(cursor, owner), 1)
            connection.commit()


if __name__ == '__main__':
    unittest.main()
