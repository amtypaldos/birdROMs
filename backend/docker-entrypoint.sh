#!/bin/sh
# birdROMs production entrypoint: apply migrations, collect static files, then start the
# given command. `gunicorn` (the default) starts the app server with env-tunable settings;
# anything else (e.g. `python manage.py createsuperuser`) is run as-is.
set -e

# Run as PUID:PGID (default 1000:1000, the usual first account on a Linux host). Started as root
# (the image default), the entrypoint gives the app's own folders to that user and drops privileges.
# Started with compose `user:` / `docker run --user`, it already runs as that user and skips this.
# The library (/library, often an NFS share) is never chowned: that user needs write access there.
# TrueNAS's `apps` account is 568; set PUID=568 PGID=568 for a share owned by that account.
if [ "$(id -u)" = "0" ]; then
    PUID="${PUID:-1000}"
    PGID="${PGID:-1000}"
    for dir in /data/media /app/staticfiles; do
        if [ -d "$dir" ] && [ "$(stat -c %u:%g "$dir")" != "$PUID:$PGID" ]; then
            chown -R "$PUID:$PGID" "$dir"
        fi
    done
    export HOME=/app
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$0" "$@"
fi

# The image may contain the handheld release that matches this server version.
# Copy it into the media volume when starting the app or another Python command.
# A shell probe (`docker run … sh -c id`) must not load Django: it has no secret key.
if [ "$1" = "gunicorn" ] || [ "$1" = "python" ]; then
    python manage.py install_bundled_handheld
fi

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
