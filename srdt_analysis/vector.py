import os
import httpx


def generate_vector(text: str) -> dict:
    response = httpx.post(
        "https://albert.api.etalab.gouv.fr/v1/embeddings",
        headers={"Authorization": f"Bearer {os.getenv('ALBERT_API_KEY')}"},
        data={
            "input": text,
            "model": "BAAI/bge-m3",
        },
    )
    vector = response.json()["data"]
    return vector
