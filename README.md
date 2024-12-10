# Assistant virtuel SRDT

## Installation et lancement

```sh
make install
pre-commit run --all-files
poetry run start # or poetry run python -m srdt_analysis
ruff check --fix
ruff format
pyright # for type checking
```

## Statistiques sur les documents

| Type de document     | Nombre |
| -------------------- | ------ |
| Code du travail      | 11,313 |
| Contributions        | 2,016  |
| Information          | 52     |
| Ministère du Travail | 1,416  |
| service-public.fr    | 527    |
