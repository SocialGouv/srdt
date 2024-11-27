import os
from typing import Any, Dict

import httpx

from srdt_analysis.constants import ALBERT_ENDPOINT


class AlbertBase:
    def __init__(self):
        self.api_key = os.getenv("ALBERT_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key must be provided either in constructor or as environment variable"
            )
        self.headers = {"Authorization": f"Bearer {self.api_key}"}

    def get_models(self) -> Dict[str, Any]:
        response = httpx.get(f"{ALBERT_ENDPOINT}/v1/models", headers=self.headers)
        return response.json()
