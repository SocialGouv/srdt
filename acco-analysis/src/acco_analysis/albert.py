"""Albert (OpenAI-compatible): embeddings and JSON chat, cached on disk so a stage can
be run again for free."""

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import numpy as np
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from acco_analysis.settings import OUT, Settings

logger = logging.getLogger(__name__)

TIMEOUT = 300
EMBED_BATCH = 32
EMBED_MAX_CHARS = 6000
CACHE = OUT / "cache"


class AlbertError(RuntimeError):
    pass


def _key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def _cached(name: str, key: str, compute: Callable[[], Any]) -> Any:
    file = CACHE / name / f"{key}.json"
    if file.exists():
        return json.loads(file.read_text())
    value = compute()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(value, ensure_ascii=False))
    return value


def run_concurrently[T, R](fn: Callable[[T], R], items: Sequence[T], workers: int):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


class Albert:
    def __init__(self, settings: Settings):
        if not settings.albert_endpoint or not settings.albert_api_key:
            raise AlbertError("ALBERT_ENDPOINT and ALBERT_API_KEY are needed")
        self.settings = settings
        self.http = httpx.Client(
            base_url=f"{settings.albert_endpoint}/v1",
            headers={"Authorization": f"Bearer {settings.albert_api_key}"},
            timeout=TIMEOUT,
        )

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        reraise=True,
    )
    def _post(self, path: str, body: dict) -> dict:
        response = self.http.post(path, json=body)
        if response.status_code in (429, 500, 502, 503, 504):
            response.raise_for_status()  # retried
        if response.is_error:
            raise AlbertError(f"{path}: {response.status_code} {response.text[:300]}")
        return response.json()

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """One row per text, in order; texts already embedded are not sent again."""
        model = self.settings.embedding_model
        texts = [t[:EMBED_MAX_CHARS] for t in texts]
        keys = [_key(model, t) for t in texts]
        missing = [
            i
            for i, k in enumerate(keys)
            if not (CACHE / "embed" / f"{k}.json").exists()
        ]
        for start in range(0, len(missing), EMBED_BATCH):
            batch = missing[start : start + EMBED_BATCH]
            data = self._post(
                "/embeddings", {"model": model, "input": [texts[i] for i in batch]}
            )["data"]
            if len(data) != len(batch):
                raise AlbertError(f"{len(data)} embeddings for {len(batch)} texts")
            for i, item in zip(batch, data, strict=True):
                _cached("embed", keys[i], lambda item=item: item["embedding"])
            logger.info(
                f"embedded {min(start + EMBED_BATCH, len(missing))}/{len(missing)}"
            )
        rows = [_cached("embed", k, lambda: None) for k in keys]
        return np.array(rows, dtype=np.float32)

    def chat_json(self, system: str, user: str, *, max_tokens: int = 4000) -> Any:
        """The JSON object the model answers with (temperature 0, cached)."""
        model = self.settings.llm_model
        key = _key(model, system, user)

        def compute() -> Any:
            body = {
                "model": model,
                "temperature": 0,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            answer = self._post("/chat/completions", body)["choices"][0]["message"]
            content = (answer.get("content") or "").strip()
            try:
                return json.loads(content)
            except json.JSONDecodeError as error:
                raise AlbertError(f"{model}: not JSON: {content[:200]!r}") from error

        return _cached("chat", key, compute)

    def chat_text(self, system: str, user: str, *, max_tokens: int = 8000) -> str:
        """The model's plain-text answer (temperature 0, cached)."""
        model = self.settings.llm_model
        key = _key("text", model, system, user)

        def compute() -> str:
            body = {
                "model": model,
                "temperature": 0,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            answer = self._post("/chat/completions", body)["choices"][0]["message"]
            content = (answer.get("content") or "").strip()
            if not content:
                raise AlbertError(f"{model}: empty answer")
            return content

        return _cached("chat_text", key, compute)
