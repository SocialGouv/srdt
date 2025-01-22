ARG NODE_VERSION=22.3.1-alpine

# dist
FROM node:$NODE_VERSION AS dist

WORKDIR /dep

# Copy lockfile
COPY ./yarn.lock ./

# Install packages
RUN yarn --frozen-lockfile

COPY . ./

RUN yarn build && \
  yarn cache clean

# app
FROM node:$NODE_VERSION

# hadolint ignore=DL3018
RUN apk --update --no-cache add ca-certificates && apk upgrade

ENV NEXT_PUBLIC_APP_ENV=production

WORKDIR /app

USER 1000

COPY --from=dist --chown=1000:1000 /dep/.next /app/.next
COPY --from=dist --chown=1000:1000 /dep/package.json /app/package.json
COPY --from=dist --chown=1000:1000 /dep/public /app/public
COPY --from=dist --chown=1000:1000 /dep/next.config.ts /app/next.config.ts
COPY --from=dist --chown=1000:1000 /dep/node_modules /app/node_modules

RUN mkdir -p /app/.next/cache/images && chown -R 1000:1000 /app/.next

CMD [ "yarn", "start"]
