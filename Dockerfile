FROM python:3.12-slim

WORKDIR /app

RUN pip install poetry==1.7.1

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
  && poetry install --no-dev --no-interaction --no-ansi

COPY . .

EXPOSE 8000

CMD ["poetry", "run", "api"]
