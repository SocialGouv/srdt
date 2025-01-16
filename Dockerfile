FROM python:3.12-slim

# Créer un utilisateur non-root avec un UID spécifique
RUN groupadd -g 1000 pythonapp && useradd -u 1000 -g pythonapp -s /bin/bash -m pythonapp

# Créer un répertoire temporaire et un répertoire home dans /app
RUN mkdir -p /app/tmp /app/home && chmod 1777 /app/tmp

# Rediriger TMPDIR et HOME vers des sous-répertoires de /app
ENV TMPDIR=/app/tmp
ENV HOME=/app/home

WORKDIR /app

# Installer Poetry en tant que root
RUN pip install poetry

# Copier les fichiers de dépendances
COPY pyproject.toml poetry.lock ./

# Installer les dépendances avec Poetry sans créer de virtualenv ni installer le projet
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-root

# Copier le code source
COPY . .

# Donner les permissions à l'utilisateur non-root
RUN chown -R 1000:1000 /app

# Passer à l'utilisateur non-root
USER 1000

EXPOSE 8000

CMD ["poetry", "run", "api"]
