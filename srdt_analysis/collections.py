import json
import time
from io import BytesIO
from typing import List

import httpx

from srdt_analysis.albert import AlbertBase
from srdt_analysis.constants import (
    ALBERT_ENDPOINT,
    COLLECTIONS_UPLOAD_BATCH_SIZE,
    COLLECTIONS_UPLOAD_DELAY_IN_SECONDS,
)
from srdt_analysis.models import (
    UUID_V4,
    CollectionName,
    DocumentData,
    RAGChunkSearchResult,
    CollectionsList,  # Add this import
)


class Collections(AlbertBase):
    def _create(self, collection_name: CollectionName, model: str) -> UUID_V4:
        payload = {"name": collection_name, "model": model}
        response = httpx.post(
            f"{ALBERT_ENDPOINT}/v1/collections", headers=self.headers, json=payload
        )
        return response.json()["id"]

    def create(self, collection_name: CollectionName, model: str) -> UUID_V4:
        collections = self.list()
        for collection in collections:
            if collection["name"] == collection_name:
                self.delete(collection["id"])
        return self._create(collection_name, model)

    def list(self) -> CollectionsList:
        try:
            response = httpx.get(
                f"{ALBERT_ENDPOINT}/v1/collections", headers=self.headers
            )
            response.raise_for_status()
            response_data = response.json()
            return response_data.get("data", [])
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
            raise ValueError(f"Error while listing collections: {str(e)}")

    def delete(self, id_collection: str) -> None:
        response = httpx.delete(
            f"{ALBERT_ENDPOINT}/v1/collections/{id_collection}", headers=self.headers
        )
        response.raise_for_status()

    def delete_all(self, collection_name: CollectionName) -> None:
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
    ) -> RAGChunkSearchResult:
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
    ) -> None:
        result = []
        for dt in data:
            dt: DocumentData
            chunks = dt["content_chunked"]
            for chunk in chunks:
                result.append(
                    {
                        "text": chunk.page_content,
                        "title": dt["title"],
                        "metadata": {
                            "id": dt["cdtn_id"],
                            "url": dt["url"],
                            "source": dt["source"],
                        },
                    }
                )

        for i in range(0, len(result), COLLECTIONS_UPLOAD_BATCH_SIZE):
            batch = result[i : i + COLLECTIONS_UPLOAD_BATCH_SIZE]
            file_content = json.dumps(batch).encode("utf-8")

            files = {
                "file": (
                    "content.json",
                    BytesIO(file_content),
                    "multipart/form-data",
                )
            }

            request_data = {"request": '{"collection": "%s"}' % id_collection}
            response = httpx.post(
                f"{ALBERT_ENDPOINT}/v1/files",
                headers=self.headers,
                files=files,
                data=request_data,
            )

            response.raise_for_status()

            if i + COLLECTIONS_UPLOAD_BATCH_SIZE < len(result):
                time.sleep(COLLECTIONS_UPLOAD_DELAY_IN_SECONDS)

        return
