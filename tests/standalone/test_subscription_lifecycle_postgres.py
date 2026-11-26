"""Real RR race: paid scheduling wins even if its access savepoint rolls back."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime
import os
from threading import Event
from types import SimpleNamespace
import unittest
from uuid import uuid4

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    psycopg2 = None

from test_subscription_contract import method, OPS


class CommercialLifecyclePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ.get('WGS_TEST_DSN')
        if not cls.dsn or not psycopg2:
            raise unittest.SkipTest('Requires explicitly disposable WGS_TEST_DSN')
        cls.schema = 'wgs_lifecycle_' + uuid4().hex
        with closing(psycopg2.connect(cls.dsn)) as connection, connection.cursor() as cursor:
            if not connection.info.dbname.startswith('wgs_test_'):
                raise RuntimeError('Refusing a non-disposable database')
            cursor.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(cls.schema)))
            cursor.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(cls.schema)))
            cursor.execute('CREATE TABLE sale_order (id integer PRIMARY KEY, write_date timestamp)')
            cursor.execute('CREATE TABLE pending_purchase (id integer PRIMARY KEY)')
            connection.commit()
        cls.version = staticmethod(method(OPS, '_wgs_version_commercial_sources'))

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
                yield connection, cursor
            connection.rollback()

    def setUp(self):
        with self.session() as (connection, cursor):
            cursor.execute('TRUNCATE sale_order, pending_purchase')
            cursor.execute("INSERT INTO sale_order VALUES (1, '2026-11-25 12:00:00')")
            connection.commit()

    def test_old_close_snapshot_must_retry_after_paid_scheduling_even_if_access_fails(self):
        snapshot_ready, paid = Event(), Event()

        def old_close():
            with self.session() as (_connection, cursor):
                cursor.execute('SELECT count(*) FROM pending_purchase')
                self.assertEqual(cursor.fetchone()[0], 0)
                snapshot_ready.set()
                self.assertTrue(paid.wait(10))
                with self.assertRaises(psycopg2.errors.SerializationFailure):
                    cursor.execute('UPDATE sale_order SET write_date = now() WHERE id = 1')

        with ThreadPoolExecutor(max_workers=1) as executor:
            closing_cron = executor.submit(old_close)
            self.assertTrue(snapshot_ready.wait(5))
            with self.session() as (connection, cursor):
                cursor.execute('SELECT id FROM sale_order WHERE id = 1 FOR UPDATE')
                self.version(SimpleNamespace(env=SimpleNamespace(cr=cursor)),
                             SimpleNamespace(ids=[1], flush_recordset=lambda: None))
                cursor.execute('INSERT INTO pending_purchase VALUES (1)')
                cursor.execute('SAVEPOINT access_projection')
                cursor.execute("UPDATE sale_order SET write_date = '2026-11-26' WHERE id = 1")
                cursor.execute('ROLLBACK TO SAVEPOINT access_projection')
                connection.commit()
            paid.set()
            closing_cron.result(timeout=12)
        with self.session() as (_connection, cursor):
            cursor.execute('SELECT write_date FROM sale_order WHERE id = 1')
            self.assertEqual(cursor.fetchone()[0], datetime(2026, 11, 25, 12))
            cursor.execute('SELECT count(*) FROM pending_purchase')
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_rejected_payment_rolls_back_source_version_and_pending_purchase(self):
        with self.session() as (connection, cursor):
            self.version(SimpleNamespace(env=SimpleNamespace(cr=cursor)),
                         SimpleNamespace(ids=[1], flush_recordset=lambda: None))
            cursor.execute('INSERT INTO pending_purchase VALUES (1)')
            connection.rollback()
        with self.session() as (_connection, cursor):
            cursor.execute('SELECT count(*) FROM pending_purchase')
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute('UPDATE sale_order SET write_date = write_date WHERE id = 1')
