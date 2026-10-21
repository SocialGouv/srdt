"""The knowledge base each question is answered with, frozen once per run.

- Fiches officielles: the documents a labeller graded at least `min_grade` for the
  question, best grade first, then in production order (rank after rerank), at most
  `max_fiches` (the web's K_RERANK). Their text is the pooled snapshot the labeller
  read.
- Code du travail: as the web's `searchArticles`, restricted to the articles cited
  by these fiches (`linked_from`), reranked, top K_RERANK_CODE.
- Convention collective: as the web's `searchIDCC`, reranked, top K_RERANK_IDCC.
- No jurisprudence.

The live searches run here only, so that every model of a run reads the same
prompt. Unlike the web, a failing search raises instead of being skipped.
"""

import asyncio
import math
from typing import Any

import httpx
from pydantic import BaseModel

from answer_eval.prompt import Chunk, ChunkMetadata
from retrieval_eval.data import DocRecord, Qrel, Query
from retrieval_eval.pipeline import IDCC_COLLECTIONS, K_RERANK, MAX_RERANK
from retrieval_eval.search_client import SearchAPI

TOP_K_CODE = 64  # web: SEARCH_OPTIONS_CODE.top_K
CODE_COLLECTIONS = ("code_du_travail",)  # web: SEARCH_OPTIONS_CODE.collections
K_RERANK_CODE = 5  # web: K_RERANK_CODE
TOP_K_IDCC = 64  # web: SEARCH_OPTIONS_IDCC.top_K
K_RERANK_IDCC = 5  # web: K_RERANK_IDCC
IDCC_LOOKUP_URL = "https://code.travail.gouv.fr/api/idcc"  # web: /api/idcc proxy


class Context(BaseModel):
    query_id: str
    text: str
    idcc: str | None = None
    # Title of the agreement, what the web sends as `agreementTitle`.
    idcc_name: str | None = None
    fiches: list[Chunk]
    code: list[Chunk]
    idcc_chunks: list[Chunk]


def select_fiches(
    query_id: str,
    qrels: list[Qrel],
    docs: dict[str, DocRecord],
    ranks: dict[tuple[str, str], int],
    *,
    min_grade: int,
    max_fiches: int,
) -> list[Chunk]:
    """Labelled documents of the query, best grade first, then production order.

    `ranks` maps (query_id, doc_id) to the rank after rerank (absent: not in the
    production ranking). A label made on another text than the snapshot is stale
    and refused."""
    chosen = [q for q in qrels if q.query_id == query_id and q.grade >= min_grade]
    chosen.sort(
        key=lambda q: (
            -q.grade,
            ranks.get((q.query_id, q.doc_id), math.inf),
            q.doc_id,
        )
    )
    fiches = []
    for qrel in chosen[:max_fiches]:
        doc = docs.get(qrel.doc_id)
        if doc is None:
            raise ValueError(f"document {qrel.doc_id} of {query_id} has no text")
        if qrel.text_sha256 and qrel.text_sha256 != doc.text_sha256:
            raise ValueError(
                f"label of {query_id}/{qrel.doc_id} was made on another text "
                "than the document snapshot"
            )
        fiches.append(
            Chunk(
                content=doc.text,
                metadata=ChunkMetadata(
                    id=doc.doc_id, source=doc.source, url=doc.url, title=doc.title
                ),
                grade=qrel.grade,
            )
        )
    return fiches


def _reranked_to_chunks(results: list[dict[str, Any]], k: int) -> list[Chunk]:
    """`rerankedToChunk` on the first k results of `/rerank`."""
    return [
        Chunk.model_validate({**r["chunk"], "rerank_score": r["rerank_score"]})
        for r in results[:k]
    ]


async def search_articles(
    api: SearchAPI, text: str, linked_from: list[str]
) -> list[Chunk]:
    """Port of `searchArticles`."""
    if not linked_from:
        return []
    chunks = await api.search(
        text,
        top_k=TOP_K_CODE,
        hybrid=True,
        collections=list(CODE_COLLECTIONS),
        linked_from=linked_from,
    )
    if not chunks:
        return []
    reranked = await api.rerank(text, chunks[:MAX_RERANK])
    return _reranked_to_chunks(reranked, K_RERANK_CODE)


async def search_idcc(api: SearchAPI, text: str, idcc: str) -> list[Chunk]:
    """Port of `searchIDCC`."""
    chunks = await api.idcc_search(
        text,
        idcc,
        top_k=TOP_K_IDCC,
        hybrid=True,
        collections=list(IDCC_COLLECTIONS),
    )
    if not chunks:
        return []
    reranked = await api.rerank(text, chunks[:MAX_RERANK])
    return _reranked_to_chunks(reranked, K_RERANK_IDCC)


async def idcc_title(client: httpx.AsyncClient, idcc: str) -> str:
    """Title of the agreement as the web's agreement picker gets it."""
    response = await client.get(IDCC_LOOKUP_URL, params={"q": idcc})
    response.raise_for_status()
    for hit in response.json()["hits"]["hits"]:
        source = hit["_source"]
        if int(source["num"]) == int(idcc):
            return source["title"]
    raise ValueError(f"IDCC {idcc} not found by {IDCC_LOOKUP_URL}")


async def build_contexts(
    queries: list[Query],
    qrels: list[Qrel],
    docs: dict[str, DocRecord],
    ranks: dict[tuple[str, str], int],
    api: SearchAPI,
    lookup: httpx.AsyncClient,
    *,
    min_grade: int = 1,
    max_fiches: int = K_RERANK,
    concurrency: int = 4,
) -> list[Context]:
    semaphore = asyncio.Semaphore(concurrency)

    async def build(query: Query) -> Context:
        fiches = select_fiches(
            query.query_id,
            qrels,
            docs,
            ranks,
            min_grade=min_grade,
            max_fiches=max_fiches,
        )
        async with semaphore:
            code = await search_articles(
                api, query.text, [f.metadata.id for f in fiches]
            )
            idcc_chunks: list[Chunk] = []
            idcc_name = None
            if query.idcc:
                idcc_chunks = await search_idcc(api, query.text, query.idcc)
                idcc_name = await idcc_title(lookup, query.idcc)
        return Context(
            query_id=query.query_id,
            text=query.text,
            idcc=query.idcc,
            idcc_name=idcc_name,
            fiches=fiches,
            code=code,
            idcc_chunks=idcc_chunks,
        )

    return list(await asyncio.gather(*(build(q) for q in queries)))
