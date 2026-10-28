#!/bin/sh
# Container entrypoint.
#   serve            back up (when migrations wait), migrate, load default sources and start gunicorn (default)
#   init [...]       bootstrap the instance (see `manage.py init --help`), e.g. init --username admin --token cli
#   manage [...]     run any manage.py command
#   <anything else>  executed as-is
set -e

cd /app

case "$1" in
  serve)
    # A backup before the database changes: only when migrations are waiting and the database has data already.
    if ! python manage.py migrate --check >/dev/null 2>&1 && python manage.py showmigrations --plan | grep -q '\[X\]'; then
      python manage.py backup --keep "${PARSIFAL_BACKUP_KEEP:-10}"
    fi
    python manage.py migrate --noinput
    python manage.py load_default_sources
    exec gunicorn parsifal.wsgi:application \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${GUNICORN_WORKERS:-2}" \
      --timeout "${GUNICORN_TIMEOUT:-120}" \
      --access-logfile - \
      --error-logfile -
    ;;
  init)
    shift
    exec python manage.py init "$@"
    ;;
  manage)
    shift
    exec python manage.py "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
