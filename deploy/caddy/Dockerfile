# Builds the SPA and serves it with Caddy (TLS, reverse proxy to the API).
# Build context: repository root.
FROM node:22-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run i18n:check && npm run build

FROM caddy:2-alpine
COPY --from=build /src/dist /srv/frontend
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
