import json
import os
from io import BytesIO
from typing import Any, Dict, List

import httpx

from srdt_analysis.constants import ALBERT_ENDPOINT, MODEL_VECTORISATION
from srdt_analysis.models import DocumentData


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

    def list(self) -> Dict[str, Any]:
        response = httpx.get(f"{ALBERT_ENDPOINT}/v1/collections", headers=self.headers)
        return response.json()

    def delete(self, collection_name: str) -> None:
        response = httpx.delete(
            f"{ALBERT_ENDPOINT}/v1/collections/{collection_name}", headers=self.headers
        )
        response.raise_for_status()
        return None

    def search(
        self,
        prompt: str,
        collections: List[str],
        k: int = 5,
        score_threshold: float = 0,
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

    def upload(
        self,
        data: list[DocumentData],
        collection_name: str,
    ) -> Dict[str, Any]:
        result = []
        for dt in data:
            dt: DocumentData
            chunks = dt["chunks"]
            for chunk in chunks:
                chunk["cdtn_id"] = dt["cdtn_id"]
                chunk["initial_id"] = dt["initial_id"]
                chunk["title"] = dt["title"]
                chunk["idcc"] = dt["idcc"]
                result.append(
                    {
                        "text": chunk["page_content"],
                        "title": dt["title"],
                        "metadata": {
                            "cdtn_id": chunk["cdtn_id"],
                            "idcc": chunk["idcc"],
                            "structure_du_chunk": chunk["metadata"],
                        },
                    }
                )

        file_content = json.dumps(result).encode("utf-8")

        files = [
            (
                "file",
                (
                    "content.json",
                    BytesIO(file_content),
                    "multipart/form-data",
                ),
            )
        ]

        data = {
            "collection": collection_name,
        }

        response = httpx.post(
            f"{ALBERT_ENDPOINT}/v1/files", headers=self.headers, files=files, data=data
        )
        return response.json()
