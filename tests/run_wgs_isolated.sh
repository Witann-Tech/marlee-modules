#!/usr/bin/env bash
# Local disposable PostgreSQL/Odoo gate. Never takes a remote database DSN.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${WGS_RUN_ISOLATED:-}" != 1 ]]; then
    echo 'Set WGS_RUN_ISOLATED=1 to create isolated, disposable local test containers.' >&2
    exit 2
fi
command -v docker >/dev/null
runtime_mount=()
runtime_command=(--entrypoint odoo odoo:19.0)
core_addons=/usr/lib/python3/dist-packages/odoo/addons
if [[ -n "${WGS_COMMUNITY_SOURCE:-}" ]]; then
    [[ -f "$WGS_COMMUNITY_SOURCE/odoo-bin" && -d "$WGS_COMMUNITY_SOURCE/addons" ]]
    runtime_mount=(-v "$WGS_COMMUNITY_SOURCE:/mnt/odoo:ro")
    runtime_command=(--entrypoint python3 odoo:19.0 /mnt/odoo/odoo-bin)
    core_addons=/mnt/odoo/addons,/mnt/odoo/odoo/addons
fi
logdir=$(mktemp -d "${TMPDIR:-/tmp}/wgs-isolated.XXXXXX")
qa="wgs-test-$(date +%s)-$$"
pg="$qa-pg"
runner="$qa-odoo"
net="$qa-net"
cleanup() {
    docker rm -f "$runner" "$pg" >/dev/null 2>&1 || true
    docker network rm "$net" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create --internal "$net" >/dev/null
docker run -d --name "$pg" --network "$net" --memory 512m --cpus 1 \
    --tmpfs /var/lib/postgresql/data:rw,size=256m \
    -e POSTGRES_USER=wgs -e POSTGRES_PASSWORD=wgs_disposable_test_only \
    -e POSTGRES_DB=wgs_test_identity postgres:16 >/dev/null
ready=0
for _ in $(seq 1 30); do
    if docker exec "$pg" pg_isready -U wgs -d wgs_test_identity >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done
[[ "$ready" == 1 ]]

module_action=-i
if [[ -n "${WGS_BASELINE_ACCESS_ADDON:-}" ]]; then
    [[ -f "$WGS_BASELINE_ACCESS_ADDON/__manifest__.py" ]]
    docker run --rm --name "$runner" --network "$net" --memory 1536m --cpus 2 \
        -v "$WGS_BASELINE_ACCESS_ADDON:/mnt/extra-addons/access_control_api:ro" \
        "${runtime_mount[@]}" "${runtime_command[@]}" --db_host="$pg" --db_user=wgs --db_password=wgs_disposable_test_only \
        -d wgs_test_identity --addons-path="/mnt/extra-addons,$core_addons" \
        -i access_control_api --without-demo --stop-after-init --max-cron-threads=0 --workers=0 --no-http \
        > "$logdir/baseline-install.log" 2>&1
    docker exec "$pg" psql -U wgs -d wgs_test_identity -v ON_ERROR_STOP=1 -c \
        "INSERT INTO access_control_person (partner_id, global_user_id, active, access_state) SELECT id, 9900, false, 'enabled' FROM res_partner ORDER BY id LIMIT 1" \
        > "$logdir/seed.log"
    module_action=-u
fi

docker run --rm --name "$runner" --network "$net" --memory 384m --cpus 1 \
    -e "WGS_TEST_DSN=host=$pg dbname=wgs_test_identity user=wgs password=wgs_disposable_test_only" \
    -e PYTHONPATH=/work/tests/standalone \
    -v "$PWD/tests:/work/tests:ro" \
    -v "$PWD/access_control_api:/work/access_control_api:ro" \
    -v "$PWD/witann_group_subscriptions_pos:/work/witann_group_subscriptions_pos:ro" \
    --entrypoint python3 odoo:19.0 -m unittest discover -s /work/tests/standalone \
    -p test_subscription_allocator_postgres.py -v > "$logdir/postgres.log" 2>&1
cat "$logdir/postgres.log"

if docker run --rm --name "$runner" --network "$net" --memory 1536m --cpus 2 \
    -v "$PWD/access_control_api:/mnt/extra-addons/access_control_api:ro" \
    "${runtime_mount[@]}" "${runtime_command[@]}" --db_host="$pg" --db_user=wgs --db_password=wgs_disposable_test_only \
    -d wgs_test_identity --addons-path="/mnt/extra-addons,$core_addons" \
    "$module_action" access_control_api --without-demo --test-enable --test-tags=/access_control_api \
    --stop-after-init --max-cron-threads=0 --workers=0 --no-http --log-level=test \
    > "$logdir/access-orm.log" 2>&1; then
    tail -12 "$logdir/access-orm.log"
else
    tail -80 "$logdir/access-orm.log"
    echo "Test logs: $logdir" >&2
    exit 1
fi
if [[ "$module_action" == -u ]]; then
    preserved=$(docker exec "$pg" psql -U wgs -d wgs_test_identity -At -v ON_ERROR_STOP=1 -c \
        'SELECT count(*) FROM access_control_person WHERE global_user_id = 9900')
    [[ "$preserved" == 1 ]]
    echo 'Upgrade preserved the pre-existing identity 9900.'
fi
echo "Test logs: $logdir"
if [[ -n "${WGS_ENTERPRISE_ADDONS:-}" ]]; then
    [[ -f "$WGS_ENTERPRISE_ADDONS/sale_subscription/__manifest__.py" ]]
    if docker run --rm --name "$runner" --network "$net" --memory 1536m --cpus 2 \
        -v "$PWD/access_control_api:/mnt/extra-addons/access_control_api:ro" \
        -v "$PWD/witann_group_subscriptions:/mnt/extra-addons/witann_group_subscriptions:ro" \
        -v "$PWD/witann_group_subscriptions_pos:/mnt/extra-addons/witann_group_subscriptions_pos:ro" \
        -v "$WGS_ENTERPRISE_ADDONS:/mnt/enterprise:ro" \
        "${runtime_mount[@]}" "${runtime_command[@]}" --db_host="$pg" --db_user=wgs --db_password=wgs_disposable_test_only \
        -d wgs_test_identity --addons-path="/mnt/extra-addons,/mnt/enterprise,$core_addons" \
        -i witann_group_subscriptions_pos --without-demo --test-enable \
        --test-tags="${WGS_TEST_TAGS:-/access_control_api,/witann_group_subscriptions,/witann_group_subscriptions_pos}" \
        --stop-after-init --max-cron-threads=0 --workers=0 --no-http --log-level=test \
        > "$logdir/commercial-orm.log" 2>&1; then
        tail -12 "$logdir/commercial-orm.log"
    else
        tail -80 "$logdir/commercial-orm.log"
        exit 1
    fi
else
    echo 'NOT RUN: WGS commercial ORM suite requires licensed WGS_ENTERPRISE_ADDONS (Odoo 19).'
    [[ "${WGS_REQUIRE_COMMERCIAL_ORM:-0}" != 1 ]] || exit 2
fi
