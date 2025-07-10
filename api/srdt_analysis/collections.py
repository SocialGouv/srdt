import json
import os

import httpx

from srdt_analysis.constants import (
    ALBERT_RERANK_MODEL,
    ALBERT_SEARCH_TIMEOUT,
)
from srdt_analysis.corpus import getChunksByIdcc
from srdt_analysis.models import (
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

    def get_contributions_idcc(self, idcc):
        contribs_idcc = getChunksByIdcc(idcc)
        return contribs_idcc

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

    def rerank(
        self,
        prompt: str,
        input: list[str],
    ) -> list[RerankedChunk]:
        response = httpx.post(
            f"{self.base_url}/v1/rerank",
            headers=self.headers,
            json={"prompt": prompt, "input": input, "model": ALBERT_RERANK_MODEL},
        )
        result = response.json()

        return result.get("data", [])

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
                    "url": dt["url"],
                    "source": dt["source"],
                    "title": dt["title"],
                }
                if dt["idcc"]:
                    chunk_metadata["idcc"] = dt["idcc"]

                chunk_text = chunk.page_content
                chunk_bytes = chunk_text.encode("utf-8")

                files = {"file": (dt['title'], chunk_bytes, "text/plain")}

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
