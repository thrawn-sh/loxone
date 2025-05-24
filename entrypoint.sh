#!/bin/bash

set -e
set -o pipefail
set -u

THIS_PATH="$(readlink --canonicalize-existing "${0}")"
THIS_NAME="$(basename "${THIS_PATH}")"
THIS_DIR="$(dirname "${THIS_PATH}")"

exec python -m loxone.monitor                                                                \
    --server="${LOXONE_SERVER}"                                                              \
    --user="${LOXONE_USER}"                                                                  \
    --password="${LOXONE_PASSWORD}"                                                          \
    --db-uri="postgres://${DATABASE_USER}:${DATABASE_PASSOWRD}@${DATABASE_HOST}/${DATABASE}" \
    --log-level="${LOG_LEVEL:INFO}"

