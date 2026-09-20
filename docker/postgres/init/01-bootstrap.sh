#!/bin/sh
# Runs once, when the container initialises an empty data directory.
# Reuses the same bootstrap script as the native (non-Docker) setup.
set -e
psql -v ON_ERROR_STOP=1 -v app_password="$NINFA_APP_PASSWORD" \
  --username "$POSTGRES_USER" --dbname postgres -f /bootstrap/bootstrap-local.sql
