FROM python:3.12-slim

# Créer un utilisateur non-root avec un UID spécifique
# 1000 est couramment utilisé comme premier UID non-root
RUN groupadd -g 1000 pythonapp && useradd -u 1000 -g pythonapp -s /bin/bash -m pythonapp

WORKDIR /app

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

# Passer à l'utilisateur non-root
USER 1000

EXPOSE 8000

CMD ["poetry", "run", "api"]
