FROM python:3.12-slim

# Créer un utilisateur non-root avec un UID spécifique
RUN groupadd -g 1000 pythonapp && useradd -u 1000 -g pythonapp -s /bin/bash -m pythonapp

# Créer les répertoires nécessaires sous /app
RUN mkdir -p /app/tmp /app/home /app/cache && chmod 1777 /app/tmp

# Rediriger TMPDIR, HOME, et POETRY_CACHE_DIR vers /app
ENV TMPDIR=/app/tmp
ENV HOME=/app/home
ENV POETRY_CACHE_DIR=/app/cache

WORKDIR /app

# Installer Poetry
RUN pip install --no-cache-dir poetry==1.7.1

# Copier les fichiers de dépendances
COPY pyproject.toml poetry.lock ./

# Installer les dépendances et le projet avec Poetry
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi

# Copier le code source
COPY . .

# Vérification des permissions pour l'utilisateur non-root
RUN chown -R 1000:1000 /app && chmod -R u+rwx /app

# Passer à l'utilisateur non-root
USER 1000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn srdt_analysis.api.main:app --host $API_HOST --port $API_PORT"]
