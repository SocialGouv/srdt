"""Python port of the fiches retrieval of `web/src/modules/api/prepare.ts`.

Keep it in step with the web code (`searchTextContent`, `mergeChunksByDocumentId`,
`searchIDCC`) and `web/src/constants.ts`: `tests/test_pipeline.py` compares the
constants with the TypeScript source. What the port does not copy on purpose:

- `/anonymize` is not called: `queries.jsonl` holds anonymised text already.
- A failing `/idcc/search` raises. The web logs it and carries on as if the IDCC
  had no chunks, which would silently change the collections searched here.
- Only the document order is kept after reranking (the web then asks `/docs/retrieve`
  for the top ten and puts them back in rerank order).
- The two rerank calls run concurrently, and an empty second batch is not sent.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

from retrieval_eval.data import Query, Ranking
from retrieval_eval.search_client import SearchAPI

MAX_RERANK = 64  # web: MAX_RERANK
K_RERANK = 10  # web: K_RERANK, what the answer generation is given
K_RERANK_IDCC = 5  # web: K_RERANK_IDCC
TOP_K_CONTENT = 200  # web: SEARCH_OPTIONS_CONTENT.top_K
TOP_K_IDCC = 64  # web: SEARCH_OPTIONS_IDCC.top_K
CONTENT_COLLECTIONS = (  # web: SEARCH_OPTIONS_CONTENT.collections
    "page_fiche_ministere_travail",
    "fiches_service_public",
    "information",
)
GENERIC_CONTRIBUTIONS = "contributions"  # added when no IDCC chunk is selected
IDCC_COLLECTIONS = ("conventions",)  # web: SEARCH_OPTIONS_IDCC.collections
RERANK_BATCHES = 2  # the web reranks the first two batches of MAX_RERANK


@dataclass(frozen=True)
class Variant:
    name: str
    hybrid: bool  # False: kNN only
    rerank: bool


VARIANTS: dict[str, Variant] = {
    v.name: v
    for v in (
        Variant("knn", hybrid=False, rerank=False),
        Variant("hybrid", hybrid=True, rerank=False),
        # What production does. Its first K_RERANK documents are what the LLM reads.
        Variant("hybrid+rerank", hybrid=True, rerank=True),
    )
}


def merge_chunks_by_document(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per `metadata.id`, best chunk first: the entry is the best chunk,
    with the contents of the document's other chunks appended in score order.
    Port of `mergeChunksByDocumentId` followed by its descending sort."""
    merged: dict[str, dict[str, Any]] = {}
    for chunk in sorted(chunks, key=lambda c: c["score"], reverse=True):
        doc_id = chunk["metadata"]["id"]
        if doc_id not in merged:
            merged[doc_id] = dict(chunk)
        else:
            merged[doc_id]["content"] += "\n\n" + chunk["content"]
    return sorted(merged.values(), key=lambda c: c["score"], reverse=True)


def rerank_batches(merged: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The slices the web sends to `/rerank`; documents past them are never reranked."""
    return [
        merged[i * MAX_RERANK : (i + 1) * MAX_RERANK] for i in range(RERANK_BATCHES)
    ]


def ranked_documents(
    reranked: list[dict[str, Any]],
) -> tuple[list[str], list[float | None]]:
    """Document ids by descending rerank score, the first occurrence of each."""
    best_first = sorted(reranked, key=lambda r: r["rerank_score"], reverse=True)
    ids: list[str] = []
    scores: list[float | None] = []
    for result in best_first:
        doc_id = result["chunk"]["metadata"]["id"]
        if doc_id not in ids:
            ids.append(doc_id)
            scores.append(result["rerank_score"])
    return ids, scores


async def idcc_chunks_selected(api: SearchAPI, text: str, idcc: str) -> int:
    """How many IDCC chunks the web would keep (port of `searchIDCC`)."""
    chunks = await api.idcc_search(
        text,
        idcc,
        top_k=TOP_K_IDCC,
        hybrid=True,
        collections=list(IDCC_COLLECTIONS),
    )
    inputs = chunks[:MAX_RERANK]
    if not inputs:
        return 0
    results = await api.rerank(text, inputs)
    return len(results[:K_RERANK_IDCC])


async def with_generic_contributions(api: SearchAPI, query: Query) -> bool:
    """The web adds `contributions` unless the IDCC pipeline selected chunks."""
    if not query.idcc:
        return True
    return await idcc_chunks_selected(api, query.text, query.idcc) < 1


async def rank_query(
    api: SearchAPI,
    query: Query,
    variants: list[str] | None = None,
    top_k: int = TOP_K_CONTENT,
) -> list[Ranking]:
    """Rank the fiches for a query with each variant (all by default)."""
    chosen = [VARIANTS[name] for name in (variants or VARIANTS)]
    contributions = await with_generic_contributions(api, query)
    collections = list(CONTENT_COLLECTIONS)
    if contributions:
        collections.append(GENERIC_CONTRIBUTIONS)

    merged_by_mode: dict[bool, list[dict[str, Any]]] = {}
    for hybrid in sorted({v.hybrid for v in chosen}):
        chunks = await api.search(
            query.text, top_k=top_k, hybrid=hybrid, collections=collections
        )
        merged_by_mode[hybrid] = merge_chunks_by_document(chunks)

    rankings = []
    for variant in chosen:
        merged = merged_by_mode[variant.hybrid]
        if variant.rerank:
            batches = await asyncio.gather(
                *(api.rerank(query.text, batch) for batch in rerank_batches(merged))
            )
            doc_ids, scores = ranked_documents([r for batch in batches for r in batch])
        else:
            doc_ids = [c["metadata"]["id"] for c in merged]
            scores = [c["score"] for c in merged]
        rankings.append(
            Ranking(
                query_id=query.query_id,
                variant=variant.name,
                doc_ids=doc_ids,
                scores=scores,
                contributions=contributions,
            )
        )
    return rankings
