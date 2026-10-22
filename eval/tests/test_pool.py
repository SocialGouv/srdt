import asyncio

import pytest
from fake_api import chunk, make_api

from retrieval_eval.data import Query, Ranking, load_docs, load_rankings, text_sha256
from retrieval_eval.pool import (
    DOCS_FILE,
    RANKINGS_FILE,
    PoolConfigError,
    build_pool,
    check_pool_config,
    describe_rankings,
    fetch_docs,
    rank_queries,
)
from retrieval_eval.search_client import SearchAPIError


def queries(n: int = 3) -> list[Query]:
    return [
        Query(query_id=f"q_{i}", text=f"question {i}", source="prod", split="dev")
        for i in range(n)
    ]


def run(coro):
    return asyncio.run(coro)


def ranking(query_id: str, variant: str, ids: list[str]) -> Ranking:
    return Ranking(
        query_id=query_id, variant=variant, doc_ids=ids, scores=[None] * len(ids)
    )


def test_build_pool_unions_the_top_of_each_variant_and_records_where_found():
    pool = build_pool(
        [
            ranking("q", "knn", ["a", "b", "c"]),
            ranking("q", "hybrid", ["b", "d", "e"]),
        ],
        depth=2,
    )
    assert pool == {
        "q": {"a": ["knn@1"], "b": ["knn@2", "hybrid@1"], "d": ["hybrid@2"]}
    }


def test_rank_queries_stores_every_variant_and_resumes(tmp_path):
    fake, api = make_api(
        search_results={False: [chunk("k", 0.9)], True: [chunk("h", 0.5)]}
    )
    variants = ["knn", "hybrid"]

    first = run(rank_queries(api, queries(), tmp_path, variants=variants, top_k=200))
    assert first.ranked == 3 and first.skipped == 0
    assert len(load_rankings(tmp_path / RANKINGS_FILE)) == 6

    calls = len(fake.calls)
    again = run(rank_queries(api, queries(), tmp_path, variants=variants, top_k=200))
    assert again.ranked == 0 and again.skipped == 3
    assert len(fake.calls) == calls


def test_a_new_variant_is_added_without_recomputing_the_others(tmp_path):
    fake, api = make_api(
        search_results={False: [chunk("k", 0.9)], True: [chunk("h", 1)]}
    )
    run(rank_queries(api, queries(1), tmp_path, variants=["knn"], top_k=200))
    fake.calls.clear()

    run(rank_queries(api, queries(1), tmp_path, variants=["knn", "hybrid"], top_k=200))

    assert [s["options"]["hybrid"] for s in fake.routes("/search")] == [True]
    assert {r.variant for r in load_rankings(tmp_path / RANKINGS_FILE)} == {
        "knn",
        "hybrid",
    }


def test_a_failing_query_is_reported_and_retried_on_resume(tmp_path):
    fake, api = make_api(search_results={True: [chunk("h", 0.5)]})
    fake.failures["/search"] = [400]  # not retryable: the first search fails

    first = run(rank_queries(api, queries(2), tmp_path, variants=["hybrid"], top_k=200))
    assert first.ranked == 1 and len(first.failed) == 1
    (failed,) = first.failed

    second = run(
        rank_queries(api, queries(2), tmp_path, variants=["hybrid"], top_k=200)
    )
    assert second.ranked == 1 and second.skipped == 1 and not second.failed
    assert {r.query_id for r in load_rankings(tmp_path / RANKINGS_FILE)} >= {failed}


def test_a_crash_leaving_a_partial_line_does_not_break_the_next_run(tmp_path):
    _, api = make_api(search_results={True: [chunk("h", 0.5)]})
    run(rank_queries(api, queries(1), tmp_path, variants=["hybrid"], top_k=200))
    path = tmp_path / RANKINGS_FILE
    path.write_text(path.read_text() + '{"query_id": "q_1", "var')

    summary = run(
        rank_queries(api, queries(2), tmp_path, variants=["hybrid"], top_k=200)
    )

    assert summary.ranked == 1
    assert {r.query_id for r in load_rankings(path)} == {"q_0", "q_1"}


def test_fetch_docs_snapshots_text_once_per_document(tmp_path):
    fake, api = make_api(docs={"a": "texte A", "b": "texte B", "c": "texte C"})
    path = tmp_path / RANKINGS_FILE
    from retrieval_eval.jsonl import append_jsonl

    append_jsonl(
        path,
        [
            ranking("q_0", "knn", ["a", "b", "z"]),
            ranking("q_1", "knn", ["b", "c"]),
        ],
    )

    fetched, missing = run(fetch_docs(api, tmp_path, depth=3))
    assert fetched == 3 and missing == ["z"]  # z is unknown to the API
    docs = load_docs(tmp_path / DOCS_FILE)
    assert docs["a"].text == "texte A"
    assert docs["a"].text_sha256 == text_sha256("texte A")
    assert docs["a"].url == "https://example.org/a"

    fake.calls.clear()
    fetched, _ = run(fetch_docs(api, tmp_path, depth=3))
    assert fetched == 0
    assert [b["ids"] for b in fake.routes("/docs/retrieve")] == [["z"]]  # only retry


def test_fetch_docs_only_takes_the_requested_depth(tmp_path):
    from retrieval_eval.jsonl import append_jsonl

    fake, api = make_api(docs={"a": "A", "b": "B"})
    append_jsonl(tmp_path / RANKINGS_FILE, [ranking("q_0", "knn", ["a", "b"])])
    run(fetch_docs(api, tmp_path, depth=1))
    assert set(load_docs(tmp_path / DOCS_FILE)) == {"a"}


def test_fetch_docs_batches_ids_by_ten(tmp_path):
    from retrieval_eval.jsonl import append_jsonl

    ids = [f"d{i}" for i in range(23)]
    fake, api = make_api(docs={i: i for i in ids})
    append_jsonl(tmp_path / RANKINGS_FILE, [ranking("q_0", "knn", ids)])
    run(fetch_docs(api, tmp_path, depth=50))
    assert sorted(len(b["ids"]) for b in fake.routes("/docs/retrieve")) == [3, 10, 10]


def test_config_refuses_a_different_query_file_or_top_k(tmp_path):
    check_pool_config(tmp_path, queries_sha256="aaa", top_k=200, variants=["knn"])
    with pytest.raises(PoolConfigError, match="queries_sha256"):
        check_pool_config(tmp_path, queries_sha256="bbb", top_k=200, variants=["knn"])
    with pytest.raises(PoolConfigError, match="top_k"):
        check_pool_config(tmp_path, queries_sha256="aaa", top_k=64, variants=["knn"])
    check_pool_config(tmp_path, queries_sha256="aaa", top_k=200, variants=["hybrid"])


def test_client_retries_server_errors_then_succeeds():
    fake, api = make_api(search_results={True: [chunk("h", 0.5)]})
    fake.failures["/search"] = [503, 429]
    chunks = run(api.search("q", top_k=10, hybrid=True, collections=["information"]))
    assert len(chunks) == 1
    assert len(fake.routes("/search")) == 3


def test_client_gives_up_after_the_retries_and_does_not_retry_client_errors():
    fake, api = make_api()
    fake.failures["/search"] = [503] * 10
    with pytest.raises(SearchAPIError, match="after retries"):
        run(api.search("q", top_k=10, hybrid=True, collections=["information"]))
    assert len(fake.routes("/search")) == 4  # 1 + 3 retries

    fake2, api2 = make_api()
    fake2.failures["/search"] = [401]
    with pytest.raises(SearchAPIError, match="HTTP 401"):
        run(api2.search("q", top_k=10, hybrid=True, collections=["information"]))
    assert len(fake2.routes("/search")) == 1


def test_client_sends_the_bearer_key_and_skips_empty_calls():
    fake, api = make_api()
    assert run(api.rerank("q", [])) == []
    assert run(api.retrieve([])) == []
    assert fake.calls == []


def test_describe_rankings_reports_pool_size():
    text = describe_rankings(
        [ranking("q_0", "knn", ["a", "b"]), ranking("q_0", "hybrid", ["b", "c"])],
        depth=2,
    )
    assert "3 (query, document) pairs" in text
