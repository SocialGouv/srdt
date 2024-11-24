# Assistant virtuel SRDT

## Installation et lancement

```sh
poetry shell
poetry install
poetry run start # or poetry run python -m srdt_analysis
black srdt_analysis
ruff check --fix
# ruff check --select I --fix # to fix import
ruff format
```

## Statistiques sur les documents

| Type de document     | Nombre |
| -------------------- | ------ |
| Code du travail      | 11,313 |
| Contributions        | 2,016  |
| Information          | 52     |
| Ministère du Travail | 1,416  |
| service-public.fr    | 527    |
