import os
import httpx
from .constants import ALBERT_ENDPOINT


class Vector:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("ALBERT_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key must be provided either in constructor or as environment variable"
            )

    def generate(self, text: str) -> dict:
        response = httpx.post(
            f"{ALBERT_ENDPOINT}/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            data={
                "input": text,
                "model": "BAAI/bge-m3",
            },
        )
        return response.json()["data"]
