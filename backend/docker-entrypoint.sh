#!/bin/sh
# birdROMs production entrypoint: apply migrations, collect static files, then start the
# given command. `gunicorn` (the default) starts the app server with env-tunable settings;
# anything else (e.g. `python manage.py createsuperuser`) is run as-is.
set -e

if [ "$1" = "gunicorn" ]; then
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
    # gthread workers keep long ROM uploads/downloads from tripping the worker timeout.
    exec gunicorn birdroms.wsgi:application \
        --bind "0.0.0.0:${PORT:-8000}" \
        --worker-class gthread \
        --workers "${GUNICORN_WORKERS:-3}" \
        --threads "${GUNICORN_THREADS:-4}" \
        --timeout "${GUNICORN_TIMEOUT:-300}" \
        --forwarded-allow-ips "${GUNICORN_FORWARDED_ALLOW_IPS:-*}" \
        --access-logfile - \
        --error-logfile -
fi

exec "$@"
