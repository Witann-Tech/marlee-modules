#!/usr/bin/env python3
"""Two real RPC transactions. Run only on a disposable staging database.

Requires an EMPTY, configured bank journal and an accountant/API credential.
Creates and retains 420 test bank transactions. No ledger cleanup or commits are
issued by this client; Odoo manages each RPC's transaction normally.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import csv
import getpass
import io
import json
import os
from threading import Barrier
import time
from uuid import uuid4
import xmlrpc.client


def main():
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument('--url', required=True)
    arguments.add_argument('--db', required=True)
    arguments.add_argument('--login', required=True)
    arguments.add_argument('--journal', required=True, type=int)
    arguments.add_argument('--date', default='12/10/2026', help='DD/MM/AAAA, in an open accounting period')
    arguments.add_argument('--disposable-staging', action='store_true', required=True)
    args = arguments.parse_args()
    secret = os.environ.get('WITANN_STAGING_API_KEY') or getpass.getpass('Staging API key/password: ')
    url = args.url.rstrip('/')
    uid = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/common').authenticate(args.db, args.login, secret, {})
    if not uid:
        raise RuntimeError('Staging authentication failed')

    def rpc(model, method, values, **kwargs):
        # A separate proxy per call avoids sharing non-threadsafe HTTP connections.
        with xmlrpc.client.ServerProxy(url + '/xmlrpc/2/object', allow_none=True) as proxy:
            return proxy.execute_kw(args.db, uid, secret, model, method, values, kwargs)

    journal = rpc('account.journal', 'read', [[args.journal]], fields=['company_id', 'bank_account_id', 'currency_id', 'type'])[0]
    if journal['type'] != 'bank' or not journal['bank_account_id']:
        raise RuntimeError('Select a configured bank journal')
    company_id = journal['company_id'][0]
    context = {'allowed_company_ids': [company_id]}
    account = rpc('res.partner.bank', 'read', [[journal['bank_account_id'][0]]], fields=['acc_number'], context=context)[0]['acc_number']
    company = rpc('res.company', 'read', [[company_id]], fields=['currency_id'], context=context)[0]
    currency_id = (journal['currency_id'] or company['currency_id'])[0]
    currency = rpc('res.currency', 'read', [[currency_id]], fields=['name'], context=context)[0]['name']
    scope = [('journal_id', '=', args.journal)]
    if rpc('account.move', 'search_count', [scope], context=context):
        raise RuntimeError('The test journal must be empty. Use a dedicated disposable staging journal.')
    prefix = 'witann_concurrency_' + uuid4().hex + '_'

    def new_wizard(start, stop):
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['CUENTA', 'FECHA', 'MONEDA', 'MOVIMIENTO', 'IMPORTE'])
        for index in range(start, stop):
            writer.writerow([account, args.date, currency, prefix + str(index), index + 1])
        return rpc('witann.bank.import', 'create', [{
            'journal_id': args.journal, 'filename': 'concurrency.csv',
            'file_data': base64.b64encode(output.getvalue().encode()).decode(),
        }], context=context)

    def import_pair(start, stop):
        wizards = [new_wizard(start, stop), new_wizard(start, stop)]
        for wizard in wizards:
            rpc('witann.bank.import', 'action_analyze', [[wizard]], context=context)
        barrier = Barrier(2)

        def worker(wizard):
            barrier.wait(timeout=30)
            started = time.perf_counter()
            collisions = 0
            try:
                rpc('witann.bank.import', 'action_import', [[wizard]], context=context)
            except xmlrpc.client.Fault as exc:
                if 'al mismo tiempo' not in exc.faultString:
                    raise
                collisions = 1
                # This is a fresh RPC transaction, with a fresh database snapshot.
                rpc('witann.bank.import', 'action_analyze', [[wizard]], context=context)
                rpc('witann.bank.import', 'action_import', [[wizard]], context=context)
            result = rpc('witann.bank.import', 'read', [[wizard]], fields=[
                'state', 'created_count', 'skipped_count', 'conflict_count', 'invalid_count',
            ], context=context)[0]
            if result['state'] != 'done' or result['conflict_count'] or result['invalid_count']:
                raise AssertionError(result)
            result.update(seconds=round(time.perf_counter() - started, 3), handled_collisions=collisions)
            return result

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, wizards))

    first = import_pair(0, 280)
    if sum(item['created_count'] for item in first) != 280:
        raise AssertionError(first)
    if sum(item['skipped_count'] for item in first) != 280:
        raise AssertionError(first)
    overlap = import_pair(140, 420)
    if sum(item['created_count'] for item in overlap) != 140:
        raise AssertionError(overlap)
    if sum(item['skipped_count'] for item in overlap) != 420:
        raise AssertionError(overlap)
    lines = rpc('account.bank.statement.line', 'search_read', [scope], fields=['witann_bank_movement', 'move_id'], context=context)
    if len(lines) != 420 or len({line['witann_bank_movement'] for line in lines}) != 420:
        raise AssertionError('Missing or duplicate bank transactions')
    if len({line['move_id'][0] for line in lines}) != 420:
        raise AssertionError('Bank transactions do not have distinct native moves')
    if rpc('account.move', 'search_count', [scope], context=context) != 420:
        raise AssertionError('Orphan or extra journal entries after concurrent imports')
    print(json.dumps({'database': args.db, 'journal': args.journal, 'first_280': first,
                      'overlap_280': overlap, 'final_lines': len(lines)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
