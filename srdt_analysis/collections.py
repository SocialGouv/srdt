import json
from io import BytesIO
from typing import Any, Dict, List

import httpx

from srdt_analysis.albert import AlbertBase
from srdt_analysis.constants import ALBERT_ENDPOINT
from srdt_analysis.models import ChunkDataList, DocumentData


class Collections(AlbertBase):
    def _create(self, collection_name: str, model: str) -> str:
        payload = {"name": collection_name, "model": model}
        response = httpx.post(
            f"{ALBERT_ENDPOINT}/v1/collections", headers=self.headers, json=payload
        )
        return response.json()["id"]

    def create(self, collection_name: str, model: str) -> str:
        collections = self.list()
        for collection in collections:
            if collection["name"] == collection_name:
                self.delete(collection["id"])
        return self._create(collection_name, model)

    def list(self) -> Dict[str, Any]:
        response = httpx.get(f"{ALBERT_ENDPOINT}/v1/collections", headers=self.headers)
        return response.json()["data"]

    def delete(self, id_collection: str):
        response = httpx.delete(
            f"{ALBERT_ENDPOINT}/v1/collections/{id_collection}", headers=self.headers
        )
        response.raise_for_status()

    def delete_all(self, collection_name) -> None:
        collections = self.list()
        for collection in collections:
            if collection["name"] == collection_name:
                self.delete(collection["id"])
        return None

    def search(
        self,
        prompt: str,
        id_collections: List[str],
        k: int = 5,
        score_threshold: float = 0,
    ) -> ChunkDataList:
        response = httpx.post(
            f"{ALBERT_ENDPOINT}/v1/search",
            headers=self.headers,
            json={
                "prompt": prompt,
                "collections": id_collections,
                "k": k,
                "score_threshold": score_threshold,
            },
        )
        return response.json()

    def upload(
        self,
        data: List[DocumentData],
        id_collection: str,
    ) -> Dict[str, Any]:
        result = []
        for dt in data:
            dt: DocumentData
            chunks = dt["chunks"]
            for chunk in chunks:
                result.append(
                    {
                        "text": chunk.page_content,
                        "title": dt["title"],
                        "metadata": {
                            "cdtn_id": dt["cdtn_id"],
                            "idcc": dt["idcc"],
                            "structure_du_chunk": chunk.metadata,
                            "url": dt["url"],
                        },
                    }
                )

        file_content = json.dumps(result).encode("utf-8")

        file_like_object = BytesIO(file_content)

        files = {
            "file": (
                "content.json",
                file_like_object,
                "multipart/form-data",
            )
        }

        data = {"request": '{"collection": "%s"}' % id_collection}
        response = httpx.post(
            f"{ALBERT_ENDPOINT}/v1/files", headers=self.headers, files=files, data=data
        )

        response.raise_for_status()
        return response.json()
