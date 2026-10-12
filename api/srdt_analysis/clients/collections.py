import json
import os

import httpx

from srdt_analysis.core.constants import (
    ALBERT_RERANK_MODEL,
    ALBERT_SEARCH_TIMEOUT,
)
from srdt_analysis.core.exceptions import (
    ConfigurationError,
    ExternalServiceError,
)
from srdt_analysis.core.models import (
    COLLECTION_ID,
    COLLECTIONS_ID,
    AlbertCollectionsList,
    CollectionName,
    DocumentData,
    ListOfDocumentData,
    RankedChunk,
    RerankedChunk,
)


class AlbertCollectionHandler:
    def __init__(self):
        self.api_key = os.getenv("ALBERT_API_KEY")
        if not self.api_key:
            raise ConfigurationError(
                "ALBERT_API_KEY environment variable is not set", service="Albert"
            )
        self.base_url = os.getenv("ALBERT_ENDPOINT")
        if not self.base_url:
            raise ConfigurationError(
                "ALBERT_ENDPOINT environment variable is not set", service="Albert"
            )
        self.model = os.getenv("ALBERT_VECTORISATION_MODEL")
        if not self.model:
            raise ConfigurationError(
                "ALBERT_VECTORISATION_MODEL environment variable is not set",
                service="Albert",
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
                f"{self.base_url}/v1/collections",
                headers=self.headers,
                params={"limit": 100},
            )
            response.raise_for_status()
            response_data = response.json()
            return response_data.get("data", [])
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
            raise ExternalServiceError(
                f"Albert service error listing collections: {str(e)}", service="Albert"
            ) from e

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

    def embeddings(
        self, chunks: list[str], timeout: int = ALBERT_SEARCH_TIMEOUT, retry=False
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

    def search(
        self,
        prompt: str,
        id_collections: COLLECTIONS_ID,
        k: int = 5,
        score_threshold: float = 0,
        timeout: int = ALBERT_SEARCH_TIMEOUT,
    ) -> list[RankedChunk]:
        try:
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
            response.raise_for_status()
            result = response.json()
            return result.get("data", [])
        except httpx.HTTPStatusError as e:
            raise ExternalServiceError(
                f"Albert search error (HTTP {e.response.status_code})", service="Albert"
            ) from e
        except (httpx.RequestError, json.JSONDecodeError) as e:
            raise ExternalServiceError(
                f"Albert search error: {str(e)}", service="Albert"
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

    def upload(
        self,
        data: ListOfDocumentData,
        id_collection: COLLECTION_ID,
    ) -> None:
        for dt in data:
            dt: DocumentData
            chunks = dt["content_chunked"]
            for chunk in chunks:
                chunk_metadata = {
                    "id": dt["cdtn_id"],
                    "initial_id": dt["initial_id"],
                    "url": dt["url"],
                    "source": dt["source"],
                    "title": dt["title"],
                }
                if dt["idcc"]:
                    chunk_metadata["idcc"] = dt["idcc"]

                chunk_text = f"{dt['title']} \n {chunk.page_content}"
                chunk_bytes = chunk_text.encode("utf-8")

                files = {"file": (dt["title"], chunk_bytes, "text/plain")}

                metadata_json = json.dumps(chunk_metadata, ensure_ascii=False)

                form_data = {
                    "collection": id_collection,
                    "chunker": "NoSplitter",
                    "metadata": metadata_json,
                }

                response = httpx.post(
                    f"{self.base_url}/v1/documents",
                    headers=self.headers,
                    files=files,
                    data=form_data,
                )

                response.raise_for_status()

        return
