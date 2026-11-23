#!/usr/bin/env bash
# Disposable local Odoo/PostgreSQL only; no ports or remote database credentials.
set -euo pipefail
cd "$(dirname "$0")/.."
qa="pos-cash-qa-$(date +%s)-$$"
logs=$(mktemp -d "${TMPDIR:-/tmp}/pos-cash-qa.XXXXXX")
cleanup() {
    docker rm -f "$qa-odoo" "$qa-pg" >/dev/null 2>&1 || true
    docker network rm "$qa-net" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create --internal "$qa-net" >/dev/null
docker run -d --name "$qa-pg" --network "$qa-net" --memory 512m --cpus 1 \
    --tmpfs /var/lib/postgresql/data:rw,size=256m \
    -e POSTGRES_USER=qa -e POSTGRES_PASSWORD=disposable_qa_only \
    -e POSTGRES_DB=pos_cash_qa postgres:16 >/dev/null
for _ in $(seq 1 30); do
    if docker exec "$qa-pg" pg_isready -U qa -d pos_cash_qa >/dev/null 2>&1; then break; fi
    sleep 1
done
echo "Test log: $logs/odoo.log"
if docker run --rm --name "$qa-odoo" --network "$qa-net" --memory 1536m --cpus 2 \
    -v "$PWD/witann_pos_cash_vendor_reconcile:/mnt/extra-addons/witann_pos_cash_vendor_reconcile:ro" \
    --entrypoint odoo odoo:19.0 --db_host="$qa-pg" --db_user=qa --db_password=disposable_qa_only \
    -d pos_cash_qa -i witann_pos_cash_vendor_reconcile --without-demo --test-enable \
    --test-tags=/witann_pos_cash_vendor_reconcile --stop-after-init --no-http \
    --max-cron-threads=0 --workers=0 --log-level=test > "$logs/odoo.log" 2>&1; then
    tail -15 "$logs/odoo.log"
else
    tail -100 "$logs/odoo.log"
    exit 1
fi
if docker run --rm -i --name "$qa-odoo" --network "$qa-net" --memory 1536m --cpus 2 \
    -e POS_CASH_DISPOSABLE_TEST=1 \
    -v "$PWD/witann_pos_cash_vendor_reconcile:/mnt/extra-addons/witann_pos_cash_vendor_reconcile:ro" \
    --entrypoint odoo odoo:19.0 shell --db_host="$qa-pg" --db_user=qa --db_password=disposable_qa_only \
    -d pos_cash_qa --no-http --max-cron-threads=0 --workers=0 \
    < tests/pos_cash_concurrency.py > "$logs/concurrency.log" 2>&1; then
    tail -8 "$logs/concurrency.log"
else
    tail -80 "$logs/concurrency.log"
    exit 1
fi
