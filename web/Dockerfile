ARG NODE_VERSION=22.12.0-alpine

# dist
FROM node:$NODE_VERSION AS dist

WORKDIR /dep

# Copy package files first
COPY package.json yarn.lock ./

# Install packages
RUN yarn --frozen-lockfile

# Copy rest of the application
COPY . .

# Build the application
RUN --mount=type="secret,id=sentry_auth_token" export SENTRY_AUTH_TOKEN=$(cat /run/secrets/sentry_auth_token); \
    export GENERATE_SOURCEMAP=true; \
    export SENTRY_ALLOW_FAILURE=true; \ 
    yarn build:standalone && \
    yarn cache clean

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
