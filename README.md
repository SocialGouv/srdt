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

### Commands

```sh
poetry run ingest # for launching the ingestion of data
poetry run api # for launching the API
```

### Lint, format and type checking

```sh
poetry run ruff check --fix # for checking and fixing
poetry run ruff format # for formatting
poetry run pyright # for type checking
poetry run pre-commit run --all-files # for running all the checks
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
