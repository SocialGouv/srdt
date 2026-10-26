import json

import httpx

from srdt_analysis.core.constants import (
    ALBERT_EMBEDDINGS_TIMEOUT,
    ALBERT_RERANK_MODEL,
)
from srdt_analysis.core.exceptions import ExternalServiceError
from srdt_analysis.core.models import (
    RerankedChunk,
)
from srdt_analysis.core.settings import get_settings


class AlbertClient:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.albert_api_key.get_secret_value()
        self.base_url = settings.albert_endpoint
        self.model = settings.albert_vectorisation_model
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
