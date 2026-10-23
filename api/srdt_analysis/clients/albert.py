import json
import os

import httpx

from srdt_analysis.core.constants import (
    ALBERT_EMBEDDINGS_TIMEOUT,
    ALBERT_RERANK_MODEL,
)
from srdt_analysis.core.exceptions import (
    ConfigurationError,
    ExternalServiceError,
)
from srdt_analysis.core.models import (
    RerankedChunk,
)


class AlbertClient:
    def __init__(self):
        self.api_key = os.getenv("ALBERT_API_KEY")
        if not self.api_key:
            raise ConfigurationError(
                "ALBERT_API_KEY environment variable is not set", service="Albert"
            )
        self.base_url = os.getenv("ALBERT_ENDPOINT")
        if not self.base_url:
            raise ConfigurationError(
                "ALBERT_ENDPOINT environment variable is not set", service="Albert"
            )
        self.model = os.getenv("ALBERT_VECTORISATION_MODEL")
        if not self.model:
            raise ConfigurationError(
                "ALBERT_VECTORISATION_MODEL environment variable is not set",
                service="Albert",
            )
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

    def embeddings(
        self, chunks: list[str], timeout: int = ALBERT_EMBEDDINGS_TIMEOUT, retry=False
    ) -> list[float]:
        try:
            response = httpx.post(
                f"{self.base_url}/v1/embeddings",
                headers=self.headers,
                json={"model": self.model, "input": chunks},
                timeout=timeout,
            )
            if response.status_code == 200:
                result = response.json()
                return [q["embedding"] for q in result["data"]]
            elif not retry:
                return self.embeddings(chunks=chunks, timeout=timeout, retry=True)
            else:
                response.raise_for_status()
                return []
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
            raise ExternalServiceError(
                f"Albert embedding service error: {str(e)}", service="Albert"
            ) from e

    def rerank(
        self,
        prompt: str,
        input: list[str],
    ) -> list[RerankedChunk]:
        try:
            response = httpx.post(
                f"{self.base_url}/v1/rerank",
                headers=self.headers,
                json={
                    "query": prompt,
                    "documents": input,
                    "model": ALBERT_RERANK_MODEL,
                },
            )
            response.raise_for_status()
            result = response.json()

            chunks = result.get("results", [])

            if len(chunks) == 0 and len(input) > 0:
                raise ExternalServiceError(
                    "Albert rerank error : no chunked received",
                    service="Albert",
                )
            else:
                return chunks
        except httpx.HTTPStatusError as e:
            raise ExternalServiceError(
                f"Albert rerank error (HTTP {e.response.status_code})", service="Albert"
            ) from e
        except (httpx.RequestError, json.JSONDecodeError) as e:
            raise ExternalServiceError(
                f"Albert rerank error: {str(e)}", service="Albert"
            ) from e
