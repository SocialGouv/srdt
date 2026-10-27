FROM ghcr.io/astral-sh/uv:0.9.5 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src ./src
COPY config ./config
COPY schema ./schema
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
RUN groupadd -g 1000 ingestion && useradd -u 1000 -g ingestion -m -d /home/ingestion ingestion
WORKDIR /app
COPY --from=build --chown=1000:1000 /app /app
ENV PATH="/app/.venv/bin:$PATH" HOME=/tmp
USER 1000
ENTRYPOINT ["ingest"]
CMD ["--help"]
