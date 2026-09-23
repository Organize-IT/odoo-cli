#!/usr/bin/env bash
# Start a throwaway Odoo (ODOO_VERSION, default 17.0) with a "test" database
# initialised with base, sale, purchase and stock, then wait until it answers.
# ODOO_PORT (default 8069) is the host port.
#
# Odoo 20 has no published image: it is built from source at the commit pinned in
# docker/odoo20/SHA, tagged odoo-src:20.0-<sha>, and reused if that tag already exists
# (CI builds it beforehand with a layer cache).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="docker compose -f ${ROOT}/docker/odoo-compose.yml"
export ODOO_VERSION="${ODOO_VERSION:-17.0}"
export ODOO_PORT="${ODOO_PORT:-8069}"

if [[ "${ODOO_VERSION}" == "20.0" ]]; then
  sha="$(tr -d '[:space:]' < "${ROOT}/docker/odoo20/SHA")"
  export ODOO_IMAGE="odoo-src:20.0-${sha:0:12}"
  if ! docker image inspect "${ODOO_IMAGE}" > /dev/null 2>&1; then
    docker build -t "${ODOO_IMAGE}" --build-arg "ODOO_SHA=${sha}" "${ROOT}/docker/odoo20"
  fi
fi

DB_ARGS=(--db_host db --db_user odoo --db_password odoo)

$COMPOSE up -d db
$COMPOSE run --rm odoo -d test -i base,sale,purchase,stock --without-demo=all \
  --stop-after-init "${DB_ARGS[@]}"
$COMPOSE up -d odoo

for _ in $(seq 1 90); do
  if curl -sf -o /dev/null "http://localhost:${ODOO_PORT}/web/login"; then
    echo "Odoo ${ODOO_VERSION} is up on http://localhost:${ODOO_PORT} (db: test, admin/admin)"
    exit 0
  fi
  sleep 2
done
echo "Odoo did not come up in time" >&2
$COMPOSE logs odoo | tail -50 >&2
exit 1
