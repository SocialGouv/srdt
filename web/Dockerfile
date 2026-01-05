ARG NODE_VERSION=22.12.0-alpine

# dist
FROM node:$NODE_VERSION AS dist

WORKDIR /dep

# Install pnpm (avoid Corepack signature/key mismatches in some base images)
RUN npm install -g pnpm@10.27.0

# Copy lock/config first so dependency fetch is cached unless the lockfile changes
COPY pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./

# Pre-fetch packages into the pnpm store (no node_modules yet)
RUN pnpm fetch

# Copy manifest separately so changing package.json does not invalidate the fetch layer
COPY package.json ./

# Install using only the pre-fetched store
RUN pnpm install --offline --frozen-lockfile

# Copy rest of the application
COPY . .

# Build the application
RUN --mount=type=secret,id=sentry_auth_token,required=false \
    if [ -f /run/secrets/sentry_auth_token ]; then export SENTRY_AUTH_TOKEN="$(cat /run/secrets/sentry_auth_token)"; fi; \
    export GENERATE_SOURCEMAP=true; \
    export SENTRY_ALLOW_FAILURE=true; \
    pnpm build:standalone && pnpm store prune

# app
FROM node:$NODE_VERSION

# hadolint ignore=DL3018
RUN apk --update --no-cache add ca-certificates && apk upgrade

WORKDIR /app

USER 1000

COPY --from=dist --chown=1000:1000 /dep/.next/standalone /app/.next/standalone
COPY --from=dist --chown=1000:1000 /dep/.next/static /app/.next/static
COPY --from=dist --chown=1000:1000 /dep/package.json /app/package.json
COPY --from=dist --chown=1000:1000 /dep/next.config.ts /app/next.config.ts

RUN mkdir -p /app/.next/cache/images && chown -R 1000:1000 /app/.next

CMD [ "node", ".next/standalone/server.js"]
