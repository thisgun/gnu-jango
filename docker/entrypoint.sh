#!/bin/sh
# Container entrypoint: apply migrations (unless RUN_MIGRATIONS=0, e.g. for workers or extra web
# replicas, so only one container migrates), then run the given command.
set -e
if [ "${RUN_MIGRATIONS:-1}" != "0" ]; then
  python manage.py migrate --noinput
fi
exec "$@"
