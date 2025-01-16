FROM python:3.12-slim

# Créer un utilisateur non-root avec un UID spécifique
RUN groupadd -g 1000 pythonapp && useradd -u 1000 -g pythonapp -s /bin/bash -m pythonapp

WORKDIR /app

# Créer et configurer un répertoire temporaire avec les bonnes permissions
RUN mkdir -p /app/tmp && \
    chown -R 1000:1000 /app/tmp && \
    chmod 1777 /app/tmp

# Configuration du répertoire temporaire
ENV TMPDIR=/app/tmp
ENV TEMP=/app/tmp
ENV TMP=/app/tmp

# Installation de poetry en tant que root
RUN pip install poetry==1.7.1

# Configurer poetry pour installer dans un répertoire local
ENV POETRY_HOME="/app/.poetry"
ENV PATH="/app/.poetry/bin:$PATH"
ENV POETRY_VIRTUALENVS_PATH="/app/.virtualenvs"
ENV PIP_TARGET="/app/lib"
ENV PYTHONPATH="/app/lib"

# Créer les répertoires nécessaires et donner les permissions
RUN mkdir -p /app/lib /app/.poetry /app/.virtualenvs && \
    chown -R 1000:1000 /app

# Copier les fichiers de dépendances
COPY pyproject.toml poetry.lock ./
RUN chown 1000:1000 pyproject.toml poetry.lock

# Passer à l'utilisateur non-root
USER 1000

# Installer les dépendances en tant qu'utilisateur non-root
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

# Copier le code source
USER root
COPY . .
RUN chown -R 1000:1000 /app

USER 1000

EXPOSE 8000

CMD ["poetry", "run", "api"]
