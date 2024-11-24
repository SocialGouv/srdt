import httpx

from srdt_analysis.albert import AlbertBase
from srdt_analysis.constants import ALBERT_ENDPOINT, MODEL_VECTORISATION


class Vector(AlbertBase):
    def generate(self, text: str) -> dict:
        response = httpx.post(
            f"{ALBERT_ENDPOINT}/v1/embeddings",
            headers=self.headers,
            json={
                "input": text,
                "model": MODEL_VECTORISATION,
            },
        )
        return response.json()["data"]
