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
yarn install --frozen-lockfile # for installing the dependencies
yarn build # for building the web app
yarn build:standalone # scripts used for building app for standalone usage
yarn dev # for running the web app in development mode
yarn start # for running the web app in production mode
yarn start:standalone # scripts used for running app for standalone usage
```

### Lint, format and type checking

```sh
yarn type-check # for type-checking
yarn lint # for linting
```

## Stats

| Type de document     | Nombre |
| -------------------- | ------ |
| Code du travail      | 11,313 |
| Contributions        | 2,016  |
| Information          | 52     |
| Ministère du Travail | 1,416  |
| service-public.fr    | 527    |

