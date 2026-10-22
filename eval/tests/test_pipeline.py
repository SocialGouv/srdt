import asyncio
import re
from pathlib import Path

import pytest
from fake_api import chunk, make_api

from retrieval_eval import pipeline
from retrieval_eval.data import Query
from retrieval_eval.pipeline import (
    VARIANTS,
    merge_chunks_by_document,
    rank_query,
    ranked_documents,
    rerank_batches,
)
from retrieval_eval.search_client import SearchAPIError

WEB_CONSTANTS = Path(__file__).parents[2] / "web/src/constants.ts"


def query(idcc: str | None = None) -> Query:
    return Query(
        query_id="q_1",
        text="Puis-je démissionner ?",
        source="prod",
        idcc=idcc,
        split="dev",
    )


def run(coro):
    return asyncio.run(coro)


def test_merge_keeps_one_entry_per_document_best_chunk_first():
    chunks = [
        chunk("b", 0.2, "b-low"),
        chunk("a", 0.9, "a-high"),
        chunk("b", 0.8, "b-high"),
        chunk("a", 0.1, "a-low"),
    ]
    merged = merge_chunks_by_document(chunks)

    assert [c["metadata"]["id"] for c in merged] == ["a", "b"]
    assert merged[0]["score"] == 0.9
    assert merged[0]["content"] == "a-high\n\na-low"  # appended in score order
    assert merged[1]["content"] == "b-high\n\nb-low"
    assert chunks[1]["content"] == "a-high"  # the input is left alone


def test_merge_is_stable_on_equal_scores():
    merged = merge_chunks_by_document(
        [chunk("x", 1.0), chunk("y", 1.0), chunk("z", 1.0)]
    )
    assert [c["metadata"]["id"] for c in merged] == ["x", "y", "z"]


def test_rerank_batches_cover_two_slices_of_64():
    merged = [chunk(f"d{i}", 1 - i / 1000) for i in range(150)]
    first, second = rerank_batches(merged)
    assert len(first) == 64 and len(second) == 64
    assert second[0]["metadata"]["id"] == "d64"
    assert "d128" not in {c["metadata"]["id"] for c in first + second}


def test_ranked_documents_sorts_by_score_across_batches_and_dedups():
    reranked = [
        {"rerank_score": 0.3, "chunk": chunk("a", 1)},
        {"rerank_score": 0.9, "chunk": chunk("b", 1)},
        {"rerank_score": 0.6, "chunk": chunk("a", 1)},
    ]
    ids, scores = ranked_documents(reranked)
    assert ids == ["b", "a"]
    assert scores == [0.9, 0.6]


def test_rank_query_returns_each_variant_with_its_own_search():
    fake, api = make_api(
        search_results={
            False: [chunk("k1", 0.9), chunk("k2", 0.8)],
            True: [chunk("h1", 0.03), chunk("h2", 0.02), chunk("h1", 0.01)],
        },
        rerank_scores={"h1": 0.1, "h2": 0.7},
    )
    rankings = {r.variant: r for r in run(rank_query(api, query()))}

    assert rankings["knn"].doc_ids == ["k1", "k2"]
    assert rankings["hybrid"].doc_ids == ["h1", "h2"]
    assert rankings["hybrid+rerank"].doc_ids == ["h2", "h1"]
    assert rankings["hybrid+rerank"].scores == [0.7, 0.1]
    # one search per mode, 200 chunks, the web's collections plus contributions
    searches = fake.routes("/search")
    assert sorted(s["options"]["hybrid"] for s in searches) == [False, True]
    assert all(s["options"]["top_K"] == 200 for s in searches)
    assert all("idcc" not in s for s in searches)
    assert searches[0]["options"]["collections"] == [
        "page_fiche_ministere_travail",
        "fiches_service_public",
        "information",
        "contributions",
    ]


def test_only_requested_variants_are_computed():
    fake, api = make_api(search_results={False: [chunk("k1", 0.9)]})
    rankings = run(rank_query(api, query(), ["knn"]))
    assert [r.variant for r in rankings] == ["knn"]
    assert len(fake.routes("/search")) == 1
    assert fake.routes("/rerank") == []


def test_empty_second_batch_is_not_sent_to_rerank():
    fake, api = make_api(search_results={True: [chunk("h1", 0.5)]})
    run(rank_query(api, query(), ["hybrid+rerank"]))
    assert len(fake.routes("/rerank")) == 1


def test_idcc_with_selected_chunks_drops_generic_contributions():
    fake, api = make_api(
        search_results={True: [chunk("h1", 0.5)]},
        idcc_chunks=[chunk("conv-1", 1)],
    )
    (ranking,) = run(rank_query(api, query(idcc="1979"), ["hybrid"]))

    assert ranking.contributions is False
    (idcc_call,) = fake.routes("/idcc/search")
    assert idcc_call["idcc"] == "1979"
    assert "contributions" not in fake.routes("/search")[0]["options"]["collections"]


def test_idcc_without_chunks_keeps_generic_contributions():
    fake, api = make_api(search_results={True: [chunk("h1", 0.5)]}, idcc_chunks=[])
    (ranking,) = run(rank_query(api, query(idcc="1979"), ["hybrid"]))

    assert ranking.contributions is True
    assert "contributions" in fake.routes("/search")[0]["options"]["collections"]


def test_no_idcc_means_no_idcc_call():
    fake, api = make_api(search_results={True: [chunk("h1", 0.5)]})
    run(rank_query(api, query(), ["hybrid"]))
    assert fake.routes("/idcc/search") == []


def test_a_failing_idcc_search_raises_instead_of_changing_the_collections():
    fake, api = make_api(search_results={True: [chunk("h1", 0.5)]})
    fake.failures["/idcc/search"] = [400]
    with pytest.raises(SearchAPIError):
        run(rank_query(api, query(idcc="1979"), ["hybrid"]))


def test_unknown_variant_is_rejected():
    _, api = make_api()
    with pytest.raises(KeyError):
        run(rank_query(api, query(), ["nope"]))


@pytest.mark.skipif(not WEB_CONSTANTS.exists(), reason="web/ not in this checkout")
def test_constants_match_the_web_source():
    source = WEB_CONSTANTS.read_text(encoding="utf-8")

    def number(name: str) -> int:
        match = re.search(rf"export const {name}\s*=\s*(\d+)", source)
        assert match, f"{name} not found in constants.ts"
        return int(match.group(1))

    assert pipeline.MAX_RERANK == number("MAX_RERANK")
    assert pipeline.K_RERANK == number("K_RERANK")
    assert pipeline.K_RERANK_IDCC == number("K_RERANK_IDCC")

    def options(name: str) -> str:
        match = re.search(rf"export const {name}[^=]*=\s*\{{(.*?)\n\}};", source, re.S)
        assert match, f"{name} not found in constants.ts"
        return match.group(1)

    content = options("SEARCH_OPTIONS_CONTENT")
    assert f"top_K: {pipeline.TOP_K_CONTENT}" in content
    assert "hybrid: true" in content
    for name in pipeline.CONTENT_COLLECTIONS:
        assert name.upper() in content  # Collection.PAGE_FICHE_MINISTERE_TRAVAIL...
    assert f"top_K: {pipeline.TOP_K_IDCC}" in options("SEARCH_OPTIONS_IDCC")


def test_variants_are_the_documented_ones():
    assert list(VARIANTS) == ["knn", "hybrid", "hybrid+rerank"]
    assert VARIANTS["hybrid+rerank"].rerank and VARIANTS["hybrid+rerank"].hybrid
    assert not VARIANTS["knn"].hybrid
