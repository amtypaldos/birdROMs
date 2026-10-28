# syntax=docker/dockerfile:1
# birdROMs backend. Targets:
#   dev  — Django runserver with the source bind-mounted (docker-compose.yml)
#   prod — gunicorn; runs migrate + collectstatic on start (docker-compose.prod.yml, default)

ARG PYTHON_VERSION=3.12

# --- deps: install the locked dependency set into /opt/venv with uv ---
# (outside /app so the dev bind mount of the source never hides it)
FROM python:${PYTHON_VERSION}-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# --- base: runtime image shared by dev and prod ---
FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    MEDIA_ROOT=/data/media \
    STATIC_ROOT=/app/staticfiles
# The app user. 568:568 is TrueNAS's built-in `apps` account, so files on a TrueNAS share are
# owned the same as other apps' (e.g. Plex). In prod, set PUID/PGID at runtime to change it
# (see docker-entrypoint.sh); the build args change the image's default user.
ARG APP_UID=568
ARG APP_GID=568
RUN groupadd --system --gid ${APP_GID} birdroms && useradd --system --uid ${APP_UID} --gid ${APP_GID} --home /app birdroms \
    && mkdir -p /data/media /library /app/staticfiles && chown -R birdroms:birdroms /data /library /app
WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
EXPOSE 8000

# --- dev: source comes from a bind mount, auto-reloads on change ---
FROM base AS dev
USER birdroms
CMD ["sh", "-c", "python manage.py migrate --noinput && exec python manage.py runserver 0.0.0.0:8000"]

# --- prod: immutable image, no secrets baked in (all config via env) ---
FROM base AS prod
COPY --chown=birdroms:birdroms . /app
RUN chmod +x /app/docker-entrypoint.sh
# Starts as root only so the entrypoint can switch to PUID/PGID (default 568:568) and drop
# privileges before anything else runs; `user:` in compose works too.
VOLUME ["/data/media"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "/app/docker-healthcheck.py"]
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn"]
