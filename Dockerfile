FROM python:3.12-slim

# Créer un utilisateur non-root avec un UID spécifique
RUN groupadd -g 1000 pythonapp && useradd -u 1000 -g pythonapp -s /bin/bash -m pythonapp

# Créer les répertoires nécessaires sous /app avec les bonnes permissions
RUN mkdir -p /app && \
    mkdir -p /app/tmp && \
    mkdir -p /app/home && \
    mkdir -p /app/cache && \
    chown -R pythonapp:pythonapp /app && \
    chmod -R 755 /app && \
    chmod 1777 /app/tmp

WORKDIR /app

# Définir les variables d'environnement après la création des répertoires
ENV TMPDIR=/app/tmp
ENV HOME=/app/home
ENV POETRY_CACHE_DIR=/app/cache

# Installer Poetry
RUN pip install --no-cache-dir poetry==2.0.1

# Copier les fichiers de dépendances
COPY pyproject.toml poetry.lock ./

# Installer les dépendances et le projet avec Poetry
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi

# Copier le code source
COPY . .

# Vérification finale des permissions
RUN chown -R pythonapp:pythonapp /app && \
    chmod -R u+rwx /app && \
    test -w $TMPDIR || exit 1

# Passer à l'utilisateur non-root
USER 1000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn srdt_analysis.api.main:app --host $API_HOST --port $API_PORT"]
