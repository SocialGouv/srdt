FROM python:3.12-slim

# Créer un utilisateur non-root avec un UID spécifique
RUN groupadd -g 1000 pythonapp && useradd -u 1000 -g pythonapp -s /bin/bash -m pythonapp

WORKDIR /app

# Créer et configurer un répertoire temporaire avec les bonnes permissions
RUN mkdir -p /app/tmp && \
    chown -R 1000:1000 /app/tmp && \
    chmod 1777 /app/tmp

# Installation de poetry en tant que root
RUN pip install poetry==1.7.1

# Copier les fichiers de dépendances
COPY pyproject.toml poetry.lock ./

# Installer les dépendances
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

# Copier le code source
COPY . .

# Définir les bonnes permissions
RUN chown -R 1000:1000 /app

# Configuration du répertoire temporaire
ENV TMPDIR=/app/tmp
ENV TEMP=/app/tmp
ENV TMP=/app/tmp

# Passer à l'utilisateur non-root
USER 1000

EXPOSE 8000

CMD ["poetry", "run", "api"]
