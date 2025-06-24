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
    --db-uri="postgres://${DATABASE_USER}:${DATABASE_PASSWORD}@${DATABASE_HOST}/${DATABASE}" \
    --backup-folder="${BACKUP_FOLDER:-/backup}"                                              \
    --log-level="${LOG_LEVEL:-INFO}"

