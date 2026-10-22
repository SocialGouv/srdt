"""An in-memory SRDT API for tests, served through httpx.MockTransport."""

import json
from collections.abc import Callable
from typing import Any

import httpx

from retrieval_eval.search_client import SearchAPI


def chunk(doc_id: str, score: float, content: str = "texte", idx: int = 0) -> dict:
    return {
        "score": score,
        "content": content,
        "id_chunk": f"{doc_id}-{idx}",
        "metadata": {
            "id": doc_id,
            "title": f"Titre {doc_id}",
            "url": f"https://example.org/{doc_id}",
            "source": "fiches_service_public",
        },
    }


class FakeAPI:
    """Records every call. `search_results` maps hybrid flag to the chunks returned;
    reranking scores a chunk by `rerank_scores[doc_id]` (default 0)."""

    def __init__(
        self,
        search_results: dict[bool, list[dict]] | None = None,
        rerank_scores: dict[str, float] | None = None,
        idcc_chunks: list[dict] | None = None,
        docs: dict[str, str] | None = None,
    ):
        self.search_results = search_results or {}
        self.rerank_scores = rerank_scores or {}
        self.idcc_chunks = idcc_chunks or []
        self.docs = docs or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.failures: dict[str, list[int]] = {}  # route -> statuses to return first

    def handler(self, request: httpx.Request) -> httpx.Response:
        route = request.url.path.removeprefix("/api/v1")
        body = json.loads(request.content)
        self.calls.append((route, body))
        statuses = self.failures.get(route)
        if statuses:
            return httpx.Response(statuses.pop(0), text="boom")
        if route == "/search":
            return httpx.Response(
                200,
                json={
                    "time": 0,
                    "top_chunks": self.search_results.get(
                        body["options"]["hybrid"], []
                    ),
                },
            )
        if route == "/anonymize":
            text = body["user_question"].replace("Monsieur", "PERSONNE")
            return httpx.Response(200, json={"time": 0, "anonymized_question": text})
        if route == "/idcc/search":
            return httpx.Response(200, json={"time": 0, "top_chunks": self.idcc_chunks})
        if route == "/rerank":
            scored = [
                {
                    "rerank_score": self.rerank_scores.get(c["metadata"]["id"], 0.0),
                    "chunk": c,
                }
                for c in body["inputs"]
            ]
            scored.sort(key=lambda r: r["rerank_score"], reverse=True)
            return httpx.Response(200, json={"time": 0, "results": scored})
        if route == "/docs/retrieve":
            contents = [
                {
                    "content": self.docs[i],
                    "metadata": {
                        "id": i,
                        "title": f"Titre {i}",
                        "url": f"https://example.org/{i}",
                        "source": "fiches_service_public",
                    },
                }
                for i in body["ids"]
                if i in self.docs
            ]
            return httpx.Response(200, json={"time": 0, "contents": contents})
        return httpx.Response(404, text=f"unexpected route {route}")

    def routes(self, name: str) -> list[dict[str, Any]]:
        return [body for route, body in self.calls if route == name]

    def api(self, **kwargs) -> SearchAPI:
        client = httpx.AsyncClient(
            base_url="http://test", transport=httpx.MockTransport(self.handler)
        )
        return SearchAPI("http://test", "key", client=client, backoff_s=0, **kwargs)


def make_api(**kwargs: Callable | Any) -> tuple[FakeAPI, SearchAPI]:
    fake = FakeAPI(**kwargs)
    return fake, fake.api()
