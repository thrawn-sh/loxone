#!/bin/bash

set -e
set -o pipefail
set -u

THIS_PATH="$(readlink --canonicalize-existing "${0}")"
THIS_NAME="$(basename "${THIS_PATH}")"
THIS_DIR="$(dirname "${THIS_PATH}")"

exec poetry run "${THIS_DIR}/loxone/monitor.py"                                              \
    --server="${LOXONE_SERVER}"                                                              \
    --user="${LOXONE_USER}"                                                                  \
    --password="${LOXONE_PASSWORD}"                                                          \
    --db-uri="postgres://${DATABASE_USER}:${DATABASE_PASSOWRD}@${DATABASE_HOST}/${DATABASE}" \
    --persist-interval="${PERSIST_INTERVAL:*/10 * * * *}"                                    \
    --log-level="${LOG_LEVEL:INFO}"

