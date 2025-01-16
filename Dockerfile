FROM python:3.12-slim

# Créer un utilisateur non-root avec un UID spécifique
RUN groupadd -g 1000 pythonapp && useradd -u 1000 -g pythonapp -s /bin/bash -m pythonapp

# Créer un répertoire temporaire avec des permissions pour l'utilisateur non-root
RUN mkdir -p /app/tmp && chmod 1777 /app/tmp

# Définir ce répertoire comme répertoire temporaire
ENV TMPDIR=/app/tmp

WORKDIR /app

# Installation des dépendances en tant que root
RUN pip install poetry

# Copier les fichiers de dépendances
COPY pyproject.toml poetry.lock ./

# Installer les dépendances en tant que root
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-root

# Copier le code source
COPY . .

ENV PYTHONPATH="/app"

# Donner les permissions à l'utilisateur non-root
RUN chown -R 1000:1000 /app

# Passer à l'utilisateur non-root pour l'exécution
USER 1000

EXPOSE 8000

CMD ["poetry", "run", "api"]
