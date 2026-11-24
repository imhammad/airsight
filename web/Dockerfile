# syntax=docker/dockerfile:1
# The public front door in production (ADR 0014): the built web app, served by Caddy, which
# also passes /v1 to the API. The Caddyfile is mounted from infra/caddy/ by docker-compose.prod.yml.

# ---------- Stage 1: build the static site ----------
# The output is plain files, so this stage runs on the build machine's own CPU even when the
# image is for another one (CI builds for Intel and Apple Silicon)
FROM --platform=$BUILDPLATFORM node:24.20.0-alpine AS build
WORKDIR /web
# Dependencies first, so this layer stays cached until the lock file changes
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# ---------- Stage 2: only the built files and Caddy ----------
FROM caddy:2.10.2-alpine
COPY --from=build /web/dist /srv
