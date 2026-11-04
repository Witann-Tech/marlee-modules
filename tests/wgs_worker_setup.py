"""Seed only the empty, disposable database used by run_wgs_isolated.sh.

Executed by odoo shell, never imported by an addon or against staging.
"""
import os


assert env.cr.dbname == 'wgs_test_identity'
assert os.environ.get('WGS_RUN_ISOLATED') == '1'
assert os.environ.get('WGS_TEST_RPC_PASSWORD')
env.ref('base.user_admin').write({
    'password': os.environ['WGS_TEST_RPC_PASSWORD'],
    'group_ids': [(4, env.ref('access_control_api.group_access_control_contact_access').id)],
})
# This is setup of an isolated test database, not a commit in a business method.
env.cr.commit()
