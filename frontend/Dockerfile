# syntax=docker/dockerfile:1
# birdROMs frontend. Targets:
#   dev  — Vite dev server with hot reload, source bind-mounted (docker-compose.yml)
#   prod — static build served by nginx, which also reverse-proxies the API to the
#          backend (docker-compose.prod.yml, default)

ARG NODE_VERSION=22

# --- deps: install with the Yarn version pinned in package.json (via corepack) ---
# Runs on the builder's own architecture: the bundle is plain JS/CSS, so a multi-arch image build
# (docker-publish.yml) does not need to emulate Node under QEMU.
FROM --platform=$BUILDPLATFORM node:${NODE_VERSION}-alpine AS deps
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    YARN_ENABLE_GLOBAL_CACHE=false \
    YARN_ENABLE_TELEMETRY=0
RUN corepack enable
WORKDIR /app
COPY package.json yarn.lock ./
RUN yarn install --immutable

# --- dev: Vite dev server; src/, index.html and vite.config.js come from bind mounts ---
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["yarn", "dev", "--host", "0.0.0.0"]

# --- build: production bundle in /app/dist ---
FROM deps AS build
COPY . .
RUN yarn build

# --- prod: nginx serving the SPA and proxying /api, /admin and /static to the backend ---
FROM nginx:1.29-alpine AS prod
# Defaults for the nginx config template; override at runtime via env.
ENV BACKEND_UPSTREAM=backend:8000 \
    NGINX_CLIENT_MAX_BODY_SIZE=2g \
    NGINX_PROXY_TIMEOUT=600s
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
