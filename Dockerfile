FROM python:3.12-slim

# Créer un utilisateur non-root avec un UID spécifique
RUN groupadd -g 1000 pythonapp && useradd -u 1000 -g pythonapp -s /bin/bash -m pythonapp

WORKDIR /app

# Installation des dépendances en tant que root
RUN pip install poetry==1.7.1

# Copier les fichiers de dépendances
COPY pyproject.toml poetry.lock ./

# Installer les dépendances en tant que root
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi

# Copier le code source
COPY . .

# Donner les permissions à l'utilisateur non-root
RUN chown -R 1000:1000 /app

# Passer à l'utilisateur non-root pour l'exécution
USER 1000

EXPOSE 8000

CMD ["poetry", "run", "api"]
