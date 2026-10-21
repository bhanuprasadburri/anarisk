#!/bin/sh
set -eu
python /app/scripts/staging/validate_url_model.py
export RUN_MIGRATIONS=false
exec /entrypoint.sh "$@"
