FROM python:3.12-slim

# Create non-root user
RUN groupadd -g 1000 pythonapp && useradd -u 1000 -g pythonapp -s /bin/bash -m pythonapp

# Create directories with proper permissions
RUN mkdir -p /tmp/app/cache && \
    mkdir -p /tmp/app/home && \
    chown -R pythonapp:pythonapp /tmp/app && \
    chmod -R 777 /tmp/app

WORKDIR /app

# Set environment variables
ENV HOME=/tmp/app/home \
    POETRY_CACHE_DIR=/tmp/app/cache \
    PYTHONPATH=/app \
    TIKTOKEN_CACHE_DIR=/tmp/app/cache

# Installer Poetry
RUN pip install --no-cache-dir poetry==2.0.1

# Copier les fichiers de dépendances
COPY pyproject.toml poetry.lock ./

# Installer les dépendances et le projet avec Poetry
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi

# Copier le code source
COPY . .

# Final permission check and directory verification
RUN chown -R pythonapp:pythonapp /app && \
    chmod -R u+rwx /app && \
    test -w $HOME || exit 1 && \
    test -w $POETRY_CACHE_DIR || exit 1

# Passer à l'utilisateur non-root
USER 1000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn srdt_analysis.api.main:app --host $API_HOST --port $API_PORT"]
