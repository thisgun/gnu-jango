#!/bin/sh
# External workers must not migrate an existing site's database on startup.
set -eu

case "${DATABASE_URL:-}" in
  postgres://*|postgresql://*) ;;
  *) echo "External workers require the existing site's PostgreSQL DATABASE_URL." >&2; exit 1 ;;
esac
if [ "${MEDIA_STORAGE:-}" != "s3" ]; then
  echo "External workers require the same S3 storage as the web deployment." >&2
  exit 1
fi
if [ "${BACKGROUND_JOBS_ENABLED:-}" != "True" ]; then
  echo "External workers require BACKGROUND_JOBS_ENABLED=True." >&2
  exit 1
fi

python manage.py check --tag compatibility
# --check exits nonzero for pending migrations; it never applies them.
python manage.py migrate --check --noinput
exec "$@"
