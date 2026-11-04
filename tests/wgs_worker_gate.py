"""Real HTTP/transaction-retry gate with two Odoo workers on a disposable DB."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
import time
import unittest
from urllib.parse import urlparse
import xmlrpc.client

import psycopg2
from psycopg2.extensions import parse_dsn


DB = 'wgs_test_identity'


class TimedTransport(xmlrpc.client.Transport):
    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = 45
        return connection


class TwoWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.environ['WGS_TEST_RPC_URL']
        cls.dsn = os.environ['WGS_TEST_DSN']
        cls.password = os.environ['WGS_TEST_RPC_PASSWORD']
        target = urlparse(cls.url)
        hostname = target.hostname or ''
        database = parse_dsn(cls.dsn)
        if (os.environ.get('WGS_RUN_ISOLATED') != '1' or database.get('dbname') != DB
                or not database.get('host', '').startswith('wgs-test-')
                or target.scheme != 'http' or not hostname.startswith('wgs-test-')
                or not hostname.endswith('-http') or target.port != 8069):
            raise RuntimeError('Worker gate requires the internal disposable Docker network.')
        deadline = time.monotonic() + 60
        while True:
            try:
                with xmlrpc.client.ServerProxy(cls.url + '/xmlrpc/2/common', transport=TimedTransport()) as common:
                    cls.uid = common.authenticate(DB, 'admin', cls.password, {})
                if not cls.uid:
                    raise RuntimeError('Disposable administrator authentication failed.')
                break
            except (OSError, xmlrpc.client.ProtocolError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.5)

    def call(self, model, method, args, **kwargs):
        with xmlrpc.client.ServerProxy(
            self.url + '/xmlrpc/2/object', transport=TimedTransport(), allow_none=True,
        ) as objects:
            return objects.execute_kw(DB, self.uid, self.password, model, method, args, kwargs)

    def partner(self, name):
        return self.call('res.partner', 'create', [{'name': name}])

    def create_person(self, partner_id):
        return self.call('access_control.person', 'create', [{
            'partner_id': partner_id, 'active': False, 'access_state': 'suspended',
        }])

    def assert_clean_transactions(self):
        with closing(psycopg2.connect(self.dsn)) as connection, connection, connection.cursor() as cursor:
            cursor.execute("""
                SELECT pid, state FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                  AND state LIKE 'idle in transaction%%'
            """, [DB])
            self.assertEqual(cursor.fetchall(), [])
            cursor.execute("SELECT id FROM ir_config_parameter WHERE key = %s FOR UPDATE NOWAIT", [
                'access_control_api.global_user_id_allocator',
            ])
            self.assertTrue(cursor.fetchone())

    def test_concurrent_http_requests_retry_stale_snapshots_with_two_workers(self):
        for iteration in range(3):
            partners = [self.partner('Worker concurrency %s/%s' % (iteration, i)) for i in range(2)]
            with closing(psycopg2.connect(self.dsn)) as connection, connection.cursor() as cursor:
                cursor.execute("UPDATE ir_config_parameter SET value = value WHERE key = %s", [
                    'access_control_api.global_user_id_allocator',
                ])
                self.assertEqual(cursor.rowcount, 1)
                # Hold the real allocator row until both HTTP workers are waiting.
                # On release, Repeatable Read snapshots must retry via Odoo itself.
                with ThreadPoolExecutor(max_workers=2) as pool:
                    jobs = [pool.submit(self.create_person, partner_id) for partner_id in partners]
                    waiters = 0
                    try:
                        deadline = time.monotonic() + 20
                        while time.monotonic() < deadline:
                            cursor.execute('SELECT pg_stat_clear_snapshot()')
                            cursor.execute("""
                                SELECT count(*) FROM pg_stat_activity
                                WHERE datname = %s AND pid <> pg_backend_pid()
                                  AND wait_event_type = 'Lock'
                                  AND query LIKE '%%ir_config_parameter%%'
                            """, [DB])
                            waiters = cursor.fetchone()[0]
                            if waiters >= 2 or any(job.done() for job in jobs):
                                break
                            time.sleep(.05)
                    finally:
                        connection.commit()
                    ids = [job.result(timeout=60) for job in jobs]
                self.assertGreaterEqual(waiters, 2, 'Both HTTP workers must really overlap.')
            rows = self.call('access_control.person', 'read', [ids], fields=['partner_id', 'global_user_id'])
            self.assertEqual({row['partner_id'][0] for row in rows}, set(partners))
            self.assertEqual(len({row['global_user_id'] for row in rows}), 2)
            self.assertTrue(all(row['global_user_id'] > 0 for row in rows))
            self.assert_clean_transactions()

    def test_repeated_requests_release_transactions_and_allocator_locks(self):
        person_id = self.create_person(self.partner('Repeated HTTP identity test'))
        before = self.call('access_control.person', 'read', [[person_id]], fields=['global_user_id'])
        for _ in range(10):
            self.call('access_control.person', 'action_assign_global_user_id', [[person_id]])
            after = self.call('access_control.person', 'read', [[person_id]], fields=['global_user_id'])
            self.assertEqual(after, before)
            self.assert_clean_transactions()


if __name__ == '__main__':
    unittest.main(verbosity=2)
