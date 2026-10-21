"""Async client of the SRDT API routes used by retrieval (no LLM involved).

The routes are those called by `web/src/modules/api/client.ts`. Chunks and reranked
chunks are passed around as plain dicts, exactly as the API returned them: `/rerank`
takes back the chunks `/search` produced.
"""

import asyncio
from typing import Any

import httpx

BASE_PATH = "/api/v1"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class SearchAPIError(RuntimeError):
    pass


class SearchAPI:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 120,
        max_retries: int = 3,
        backoff_s: float = 1.0,
    ):
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout_s
        )
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._max_retries = max_retries
        self._backoff_s = backoff_s

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _post(self, route: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{BASE_PATH}{route}"
        last = "no attempt"
        for attempt in range(self._max_retries + 1):
            if attempt:
                await asyncio.sleep(self._backoff_s * 2 ** (attempt - 1))
            try:
                response = await self._client.post(
                    url, json=body, headers=self._headers
                )
            except httpx.TransportError as e:
                last = f"{type(e).__name__}: {e}"
                continue
            if response.status_code in RETRYABLE_STATUS:
                last = f"HTTP {response.status_code}: {response.text[:200]}"
                continue
            if response.status_code >= 400:
                raise SearchAPIError(
                    f"POST {url}: HTTP {response.status_code}: {response.text[:300]}"
                )
            return response.json()
        raise SearchAPIError(f"POST {url} failed after retries: {last}")

    async def anonymize(self, text: str) -> str:
        """`/anonymize`, the first step of the web: the text it then searches."""
        data = await self._post("/anonymize", {"user_question": text})
        return data["anonymized_question"]

    async def search(
        self,
        prompt: str,
        *,
        top_k: int,
        hybrid: bool,
        collections: list[str],
        linked_from: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """`/search`, as the web calls it: no `idcc`, `threshold` left at 0.

        `linked_from` restricts the search to the chunks cited by these documents
        (the web's `searchArticles`: Code du travail articles of the fiches)."""
        options: dict[str, Any] = {
            "top_K": top_k,
            "hybrid": hybrid,
            "collections": collections,
        }
        if linked_from is not None:
            options["linked_from"] = linked_from
        data = await self._post("/search", {"prompts": [prompt], "options": options})
        return data["top_chunks"]

    async def idcc_search(
        self,
        prompt: str,
        idcc: str,
        *,
        top_k: int,
        hybrid: bool,
        collections: list[str],
    ) -> list[dict[str, Any]]:
        data = await self._post(
            "/idcc/search",
            {
                "prompts": [prompt],
                "idcc": idcc,
                "options": {
                    "top_K": top_k,
                    "hybrid": hybrid,
                    "collections": collections,
                },
            },
        )
        return data["top_chunks"]

    async def rerank(
        self, prompt: str, chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """`/rerank`: `[{rerank_score, chunk}]`, best first. Nothing is sent for an
        empty input (the route would fail on it)."""
        if not chunks:
            return []
        data = await self._post("/rerank", {"prompt": prompt, "inputs": chunks})
        return data["results"]

    async def retrieve(self, doc_ids: list[str]) -> list[dict[str, Any]]:
        """`/docs/retrieve`: full document contents `[{content, metadata}]`.

        The order of the result is the one of Elasticsearch, not of `doc_ids`."""
        if not doc_ids:
            return []
        data = await self._post("/docs/retrieve", {"ids": doc_ids})
        return data["contents"]
