#!/usr/bin/env bash
# Start a throwaway Odoo (ODOO_VERSION, default 17.0) with a "test" database
# initialised with base, sale, purchase and stock, then wait until it answers.
set -euo pipefail

COMPOSE="docker compose -f $(dirname "$0")/../docker/odoo-compose.yml"
export ODOO_VERSION="${ODOO_VERSION:-17.0}"

$COMPOSE up -d db
$COMPOSE run --rm odoo odoo -d test -i base,sale,purchase,stock --without-demo=all --stop-after-init
$COMPOSE up -d odoo

for _ in $(seq 1 90); do
  if curl -sf -o /dev/null http://localhost:8069/web/login; then
    echo "Odoo ${ODOO_VERSION} is up on http://localhost:8069 (db: test, admin/admin)"
    exit 0
  fi
  sleep 2
done
echo "Odoo did not come up in time" >&2
$COMPOSE logs odoo | tail -50 >&2
exit 1
