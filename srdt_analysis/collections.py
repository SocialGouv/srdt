import os
from typing import Any, Dict, List

import httpx

from srdt_analysis.constants import ALBERT_ENDPOINT, MODEL_VECTORISATION


class Collections:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("ALBERT_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key must be provided either in constructor or as environment variable"
            )
        self.headers = {"Authorization": f"Bearer {self.api_key}"}

    def create(self, collection_name: str) -> Dict[str, Any]:
        payload = {"name": collection_name, "model": MODEL_VECTORISATION}

        response = httpx.post(
            f"{ALBERT_ENDPOINT}/v1/collections", headers=self.headers, json=payload
        )
        return response.json()

    def delete(self, collection_name: str) -> None:
        response = httpx.delete(
            f"{ALBERT_ENDPOINT}/v1/collections/{collection_name}", headers=self.headers
        )
        response.raise_for_status()
        return None

    def search(
        self, prompt: str, collections: List[str], k: int = 5, score_threshold: float = 0
    ) -> Dict[str, Any]:
        response = httpx.post(
            f"{ALBERT_ENDPOINT}/v1/search",
            headers=self.headers,
            json={
                "prompt": prompt,
                "collections": collections,
                "k": k,
                "score_threshold": score_threshold,
            },
        )
        return response.json()
