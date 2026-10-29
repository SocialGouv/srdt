# Assistant virtuel SRDT

## Running with Docker

```sh
docker compose up -d --build
```

## API

## Configuration

```sh
cd api # to go to the api directory
cp .env.example .env # and set your own env variable
make install # for installing hooks and the dependencies
```

### Search engine

The api and the ingestion read the same variables and must use the same engine:

| Variable | Value |
|---|---|
| `SEARCH_ENGINE` | `opensearch` (default) or `elasticsearch` |
| `SEARCH_HOSTNAME` | `http://localhost:9201` for the OpenSearch of `docker compose up -d opensearch`, `http://localhost:9202` for `docker compose --profile elasticsearch up -d elasticsearch` |
| `SEARCH_CREDENTIALS` | `user:password`, or the base64 token of it |

`ELASTIC_API_KEY` still works as the former name of `SEARCH_CREDENTIALS`: the deployed sealed secrets hold it. The deployed environments set `SEARCH_ENGINE: elasticsearch`. An index is built for one engine: after switching, run `uv run ingest index` again.

### Commands

```sh
poetry run api # for launching the API
poetry run pytest # for running the tests
```

### Lint, format and type checking

```sh
poetry run ruff check --fix # for checking and fixing
poetry run ruff format # for formatting
poetry run pyright # for type checking
poetry run pre-commit run --all-files # for running all the checks
```

## Ingestion

The search index is built by the separate [`ingestion/`](ingestion/README.md) project (uv), which publishes the format of the indexed chunks as a JSON schema.

```sh
cd ingestion
cp .env.example .env # and set your own env variable
uv sync
uv run ingest fetch legi # snapshot a raw source to S3
uv run ingest index # build the index
```

## Web

## Configuration

```sh
cd web # to go to the web directory
cp .env.example .env # and set your own env variable
```

### Commands

```sh
pnpm install --frozen-lockfile # for installing the dependencies
pnpm build # for building the web app
pnpm build:standalone # scripts used for building app for standalone usage
pnpm dev # for running the web app in development mode
pnpm start # for running the web app in production mode
pnpm start:standalone # scripts used for running app for standalone usage
```

### Lint, format and type checking

```sh
pnpm type-check # for type-checking
pnpm lint # for linting
```

## Supply-chain hardening (pnpm)

This repository enforces stricter install policies to reduce supply-chain risk:

- Minimum package age: installs refuse packages published less than 72 hours ago.
  - Configured via [`minimum-release-age`](.npmrc:1) (also applied in [`web/.npmrc`](web/.npmrc:1)).
- Trust policy: pnpm will fail if trust evidence is downgraded.
  - Configured via [`trust-policy`](.npmrc:4).
- Dependency build scripts are blocked by default and must be explicitly approved.
  - Configured via [`strict-dep-builds`](.npmrc:7).
  - Approvals are recorded in [`web/pnpm-workspace.yaml`](web/pnpm-workspace.yaml:1) under [`onlyBuiltDependencies`](web/pnpm-workspace.yaml:1).

## Stats

| Type de document     | Nombre |
| -------------------- | ------ |
| Code du travail      | 11,313 |
| Contributions        | 2,016  |
| Information          | 52     |
| Ministère du Travail | 1,416  |
| service-public.fr    | 527    |
