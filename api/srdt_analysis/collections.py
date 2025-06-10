import json
import os
import time
from io import BytesIO

import httpx

from srdt_analysis.constants import (
    ALBERT_SEARCH_TIMEOUT,
    COLLECTIONS_UPLOAD_BATCH_SIZE,
    COLLECTIONS_UPLOAD_DELAY_IN_SECONDS,
)
from srdt_analysis.models import (
    COLLECTION_ID,
    COLLECTIONS_ID,
    AlbertCollectionsList,
    CollectionName,
    DocumentData,
    ListOfDocumentData,
    RankedChunk,
)


class AlbertCollectionHandler:
    def __init__(self):
        self.api_key = os.getenv("ALBERT_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key must be provided either in constructor or as environment variable"
            )
        self.base_url = os.getenv("ALBERT_ENDPOINT")
        if not self.base_url:
            raise ValueError(
                "Albert endpoint must be provided either in constructor or as environment variable"
            )
        self.model = os.getenv("ALBERT_VECTORISATION_MODEL")
        if not self.model:
            raise ValueError(
                "Albert model must be provided either in constructor or as environment variable"
            )
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

    def _create(self, collection_name: CollectionName) -> COLLECTION_ID:
        payload = {"name": collection_name, "model": self.model}
        response = httpx.post(
            f"{self.base_url}/v1/collections", headers=self.headers, json=payload
        )
        return response.json()["id"]

    def create(self, collection_name: CollectionName) -> COLLECTION_ID:
        collections = self.list_collections()
        for collection in collections:
            if collection["name"] == collection_name:
                self.delete(collection["id"])
        return self._create(collection_name)

    def list_collections(self) -> AlbertCollectionsList:
        try:
            response = httpx.get(
                f"{self.base_url}/v1/collections", headers=self.headers
            )
            response.raise_for_status()
            response_data = response.json()
            return response_data.get("data", [])
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
            raise ValueError(f"Error while listing collections: {str(e)}")

    def delete(self, id_collection: str) -> None:
        response = httpx.delete(
            f"{self.base_url}/v1/collections/{id_collection}", headers=self.headers
        )
        response.raise_for_status()

    def delete_all(self, collection_name: CollectionName) -> None:
        collections = self.list_collections()
        for collection in collections:
            if collection["name"] == collection_name:
                self.delete(collection["id"])
        return None

    def search(
        self,
        prompt: str,
        id_collections: COLLECTIONS_ID,
        k: int = 5,
        score_threshold: float = 0,
        timeout: int = ALBERT_SEARCH_TIMEOUT,
    ) -> list[RankedChunk]:
        response = httpx.post(
            f"{self.base_url}/v1/search",
            headers=self.headers,
            json={
                "prompt": prompt,
                "collections": id_collections,
                "k": k,
                "score_threshold": score_threshold,
            },
            timeout=timeout,
        )
        result = response.json()
        return result.get("data", [])

    def upload(
        self,
        data: ListOfDocumentData,
        id_collection: COLLECTION_ID,
    ) -> None:
        result = []
        for dt in data:
            dt: DocumentData
            chunks = dt["content_chunked"]
            for chunk in chunks:
                metadata = {
                    "id": dt["cdtn_id"],
                    "url": dt["url"],
                    "source": dt["source"],
                    "title": dt["title"],
                }
                if dt["idcc"]:
                    metadata["idcc"] = dt["idcc"]

                result.append(
                    {
                        "text": chunk.page_content,
                        "title": dt["title"],
                        "metadata": metadata,
                    }
                )

        for i in range(0, len(result), COLLECTIONS_UPLOAD_BATCH_SIZE):
            batch = result[i : i + COLLECTIONS_UPLOAD_BATCH_SIZE]
            file_content = json.dumps(batch).encode("utf-8")

            files = {
                "file": (
                    "content.json",
                    BytesIO(file_content),
                    "application/json",
                )
            }

            request_data = {
                "request": '{"collection": "%s", "chunker": {"name": "NoChunker"}}'
                % id_collection
            }
            response = httpx.post(
                f"{self.base_url}/v1/files",
                headers=self.headers,
                files=files,
                data=request_data,
            )

            response.raise_for_status()

            time.sleep(COLLECTIONS_UPLOAD_DELAY_IN_SECONDS)

        return
