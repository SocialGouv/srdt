"""Dense embeddings from Albert's OpenAI-compatible /v1/embeddings endpoint."""

from collections.abc import Iterator, Sequence
from typing import Protocol

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ingestion.settings import Settings, secret

TIMEOUT = 180


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class AlbertEmbedder:
    def __init__(self, settings: Settings, dim: int):
        settings.require(
            "albert_endpoint", "albert_api_key", "albert_vectorisation_model"
        )
        self.url = f"{settings.albert_endpoint}/v1/embeddings"
        self.model = settings.albert_vectorisation_model
        self.headers = {"Authorization": f"Bearer {secret(settings.albert_api_key)}"}
        self.dim = dim
        self.http = httpx.Client(timeout=TIMEOUT)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts)

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = self.http.post(
            self.url,
            headers=self.headers,
            json={"model": self.model, "input": list(texts)},
        )
        response.raise_for_status()
        vectors = [item["embedding"] for item in response.json()["data"]]
        if len(vectors) != len(texts):
            raise ValueError(f"{len(vectors)} embeddings for {len(texts)} texts")
        for vector in vectors:
            if len(vector) != self.dim:
                raise ValueError(
                    f"Embedding of size {len(vector)}, expected {self.dim} "
                    f"(model {self.model})"
                )
        return vectors


def batched[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
