"""Choosing the labeller: model-free sampling, label pairs of a key, probe, compare."""

import asyncio
import json
from collections import Counter
from pathlib import Path

import httpx
import numpy as np
import pytest
from conftest import ROOT
from openai import AsyncOpenAI
from sklearn.metrics import cohen_kappa_score

from judge_eval.judge import ModelConfig, load_models
from retrieval_eval.audit import (
    AuditItem,
    export_sheet,
    load_key,
    sample_pool_pairs,
    subset_items,
)
from retrieval_eval.data import DocRecord, Qrel, Query, Ranking, text_sha256
from retrieval_eval.labeller import (
    GradeLabeller,
    LabelFailure,
    LabelPromptBook,
    label_pairs,
    pairs_from_key,
    probe_labellers,
)
from retrieval_eval.report import compare_labellers, render_compare

PROMPTS_ROOT = ROOT / "retrieval" / "prompts"


def run(coro):
    return asyncio.run(coro)


# --- model-free sampling ------------------------------------------------------


def pool_world(n_queries: int = 30, per_variant: int = 12):
    """Every query ranks d0..d11 in production and d6..d17 in knn: the pool holds
    d0..d17, with d6..d11 found by both variants."""
    queries = {
        f"q{i}": Query(
            query_id=f"q{i}", text=f"question {i}", source="prod", split="dev"
        )
        for i in range(n_queries)
    }
    docs = {
        f"d{j}": DocRecord(
            doc_id=f"d{j}",
            title=f"Fiche {j}",
            source="information",
            text=f"texte {j}",
            text_sha256=text_sha256(f"texte {j}"),
        )
        for j in range(18)
    }
    rankings = []
    for i in range(n_queries):
        prod = [f"d{j}" for j in range(per_variant)]
        knn = [f"d{j}" for j in range(6, 6 + per_variant)]
        for variant, ids in (("hybrid+rerank", prod), ("knn", knn)):
            rankings.append(
                Ranking(
                    query_id=f"q{i}",
                    variant=variant,
                    doc_ids=ids,
                    scores=[None] * len(ids),
                )
            )
    return queries, docs, rankings


def test_pool_sample_is_stratified_on_provenance_capped_and_reproducible():
    queries, docs, rankings = pool_world()
    ids = set(queries)
    items = sample_pool_pairs(rankings, docs, ids, depth=12, n=60, seed=1)

    assert len(items) == 60
    assert max(Counter(i.query_id for i in items).values()) <= 3
    assert all(i.llm_grade is None for i in items)  # no model was involved
    # production top 10 = d0..d9; found by both variants = d6..d11
    cells = Counter(
        (i.in_production_top, int(i.doc_id[1:]) in range(6, 12)) for i in items
    )
    assert len(cells) == 4 and min(cells.values()) >= 8  # 15 each, a few shifted
    assert items == sample_pool_pairs(rankings, docs, ids, depth=12, n=60, seed=1)
    assert items != sample_pool_pairs(rankings, docs, ids, depth=12, n=60, seed=2)
    assert len({i.audit_id for i in items}) == 60
    assert all(i.text_sha256 == docs[i.doc_id].text_sha256 for i in items)


def test_pool_sample_flags_production_top_ten_membership():
    queries, docs, rankings = pool_world(n_queries=2)
    items = sample_pool_pairs(
        rankings, docs, set(queries), depth=12, n=100, seed=0, per_query_cap=100
    )
    for item in items:
        assert item.in_production_top == (int(item.doc_id[1:]) < 10)


def test_pool_sample_skips_documents_without_a_snapshot_and_other_queries():
    queries, docs, rankings = pool_world(n_queries=3)
    del docs["d0"]
    items = sample_pool_pairs(
        rankings, docs, {"q0", "q1"}, depth=12, n=500, seed=0, per_query_cap=100
    )
    assert {i.query_id for i in items} == {"q0", "q1"}
    assert "d0" not in {i.doc_id for i in items}


def test_pool_sample_depth_limits_the_pool():
    queries, docs, rankings = pool_world(n_queries=1)
    items = sample_pool_pairs(
        rankings, docs, set(queries), depth=3, n=100, seed=0, per_query_cap=100
    )
    # production d0..d2 plus knn d6..d8
    assert {i.doc_id for i in items} == {"d0", "d1", "d2", "d6", "d7", "d8"}


def test_subset_redraws_under_fresh_ids_and_is_reproducible():
    queries, docs, rankings = pool_world()
    items = sample_pool_pairs(rankings, docs, set(queries), 12, 60, 1)
    subset = subset_items(items, 30, seed=5)

    assert len(subset) == 30
    assert all(s.audit_id.startswith("b") for s in subset)
    assert len({s.audit_id for s in subset}) == 30
    originals = {(i.query_id, i.doc_id) for i in items}
    assert {(s.query_id, s.doc_id) for s in subset} <= originals
    assert subset == subset_items(items, 30, seed=5)
    assert [s.doc_id for s in subset] != [i.doc_id for i in items[:30]]
    assert len(subset_items(items, 500, seed=0)) == 60  # cannot exceed the key


def test_key_round_trip_through_export(tmp_path: Path):
    queries, docs, rankings = pool_world(n_queries=5)
    items = sample_pool_pairs(rankings, docs, set(queries), 12, 12, 0)
    sheet, key = tmp_path / "s.csv", tmp_path / "k.json"
    assert export_sheet(items, queries, docs, sheet, key) == 12
    assert load_key(key) == items
    assert json.loads(key.read_text())[0]["llm_grade"] is None


# --- label the pairs of a key -------------------------------------------------


def item(qid="q0", doc="d1", text="texte 1") -> AuditItem:
    return AuditItem(
        audit_id="a0001",
        query_id=qid,
        doc_id=doc,
        text_sha256=text_sha256(text),
        in_production_top=True,
    )


def test_pairs_from_key_keeps_usable_pairs_in_key_order():
    queries, docs, _ = pool_world(n_queries=2)
    items = [item("q1", "d3", "texte 3"), item("q0", "d1", "texte 1")]
    pairs, unusable = pairs_from_key(items, queries, docs)
    assert [(q.query_id, d.doc_id) for q, d in pairs] == [("q1", "d3"), ("q0", "d1")]
    assert unusable == []


def test_pairs_from_key_rejects_changed_missing_and_unknown_and_dedups():
    queries, docs, _ = pool_world(n_queries=2)
    items = [
        item("q0", "d1", "texte 1"),
        item("q0", "d1", "texte 1"),  # duplicate
        item("q0", "d2", "an older text"),  # the text changed since the draw
        item("q0", "zz", "x"),  # no snapshot
        item("q9", "d1", "texte 1"),  # unknown query
    ]
    pairs, unusable = pairs_from_key(items, queries, docs)
    assert [(q.query_id, d.doc_id) for q, d in pairs] == [("q0", "d1")]
    assert len(unusable) == 3


def completion(content: str) -> dict:
    return {
        "id": "c",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


def make_labeller(handler, max_chars: int, name: str = "m") -> GradeLabeller:
    client = AsyncOpenAI(
        api_key="test",
        base_url="http://llm.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    config = ModelConfig(name=name, base_url="http://llm.test/v1", model="model-x")
    prompts = LabelPromptBook(PROMPTS_ROOT, "v1", max_chars=max_chars)
    return GradeLabeller(config, prompts, client=client)


def answering(grade: int):
    def handler(request):
        return httpx.Response(
            200, json=completion(json.dumps({"reasoning": "r", "grade": grade}))
        )

    return handler


def test_a_changed_document_length_limit_is_a_new_experiment(tmp_path: Path):
    """Same labeller, same prompt version, other `max_chars`: labels are not reused."""
    queries, docs, _ = pool_world(n_queries=1)
    pairs = [(queries["q0"], docs["d1"])]
    path = tmp_path / "qrels.jsonl"
    calls = []

    def handler(request):
        calls.append(1)
        return answering(1)(request)

    first = run(label_pairs(make_labeller(handler, 12000), pairs, path))
    same = run(label_pairs(make_labeller(handler, 12000), pairs, path))
    other = run(label_pairs(make_labeller(handler, 60000), pairs, path))

    assert (first.labelled, same.skipped, other.labelled) == (1, 1, 1)
    assert len(calls) == 2
    shas = {json.loads(line)["prompt_sha256"] for line in path.read_text().splitlines()}
    assert len(shas) == 2 and "" not in shas


def test_labels_record_latency_and_the_prompt_hash(tmp_path: Path):
    queries, docs, _ = pool_world(n_queries=1)
    path = tmp_path / "q.jsonl"
    labeller = make_labeller(answering(2), 60000)
    run(label_pairs(labeller, [(queries["q0"], docs["d0"])], path))
    (record,) = [json.loads(line) for line in path.read_text().splitlines()]
    assert record["latency_s"] is not None and record["latency_s"] >= 0
    assert record["prompt_sha256"] == labeller.label_prompts.sha256


# --- probe --------------------------------------------------------------------


def probe_client(handler) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key="test",
        base_url="http://llm.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )


def test_probe_reports_ok_unserved_and_broken_models_without_stopping():
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {"id": "good", "object": "model"},
                        {"id": "garbled", "object": "model"},
                    ],
                },
            )
        body = json.loads(request.content)
        reply = (
            "no json" if body["model"] == "garbled" else '{"reasoning":"r","grade":2}'
        )
        return httpx.Response(200, json=completion(reply))

    configs = [
        ModelConfig(name="ok", base_url="http://llm.test/v1", model="good"),
        ModelConfig(name="typo", base_url="http://llm.test/v1", model="goood"),
        ModelConfig(name="bad", base_url="http://llm.test/v1", model="garbled"),
    ]
    prompts = LabelPromptBook(PROMPTS_ROOT, "v1")
    probes = run(probe_labellers(configs, prompts, lambda c: probe_client(handler)))

    ok, typo, bad = probes
    assert ok.ok and ok.grading.grade == 2 and ok.grading.response_mode == "json_schema"
    assert not typo.ok and "not served" in typo.skipped
    assert not bad.ok and bad.grading.status == "parse_error"
    assert [p.config.name for p in probes] == ["ok", "typo", "bad"]


def test_probe_reports_a_missing_key_and_keeps_going(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    configs = [
        ModelConfig(
            name="nokey",
            base_url="http://llm.test/v1",
            model="m",
            api_key_env="NOPE_KEY",
        )
    ]
    (probe,) = run(probe_labellers(configs, LabelPromptBook(PROMPTS_ROOT, "v1")))
    assert not probe.ok and "NOPE_KEY" in probe.skipped


def test_the_candidates_file_loads_and_has_no_alias_or_duplicate():
    configs = load_models(ROOT / "config" / "labellers.toml")
    assert len(configs) == 8
    models = [c.model for c in configs]
    assert not any(m.endswith("-latest") or m.startswith("openweight") for m in models)
    assert len({(c.provider, c.model) for c in configs}) == 8


# --- compare ------------------------------------------------------------------


def human_world(n_queries: int = 24, per_query: int = 5, seed: int = 0):
    rng = np.random.default_rng(seed)
    keys = [
        (f"q{q}", f"d{d}", f"sha{q}{d}")
        for q in range(n_queries)
        for d in range(per_query)
    ]
    grades = {k: int(rng.integers(0, 3)) for k in keys}
    human = [
        Qrel(query_id=q, doc_id=d, grade=g, labeller="human:r", text_sha256=sha)
        for (q, d, sha), g in grades.items()
    ]
    return keys, grades, human


def model_qrels(name, keys, grades, grade_of, latency=1.0):
    return [
        Qrel(
            query_id=q,
            doc_id=d,
            grade=grade_of(grades[(q, d, sha)], i),
            labeller=name,
            text_sha256=sha,
            latency_s=latency,
            prompt_tokens=3000,
            completion_tokens=40,
        )
        for i, (q, d, sha) in enumerate(keys)
    ]


def noisy(rate: float, seed: int = 1):
    rng = np.random.default_rng(seed)

    def grade_of(grade, i):
        if rng.random() < rate:
            return int(np.clip(grade + rng.choice([-1, 1]), 0, 2))
        return grade

    return grade_of


@pytest.fixture
def compared():
    keys, grades, human = human_world()
    models = {
        "llm:exact": model_qrels("llm:exact", keys, grades, lambda g, i: g, 3.0),
        "llm:exact-fast": model_qrels(
            "llm:exact-fast", keys, grades, lambda g, i: g, 1.0
        ),
        "llm:close": model_qrels("llm:close", keys, grades, noisy(0.12), 2.0),
        "llm:poor": model_qrels("llm:poor", keys, grades, noisy(0.9, seed=2), 0.5),
        "llm:constant": model_qrels("llm:constant", keys, grades, lambda g, i: 1, 0.2),
    }
    return keys, grades, human, models


def test_compare_ranks_models_and_applies_the_bar(compared):
    keys, grades, human, models = compared
    result = compare_labellers(human, models, n_boot=400, seed=0)
    table = result.table.set_index("model")

    assert result.best in {"llm:exact", "llm:exact-fast"}
    assert table.loc["llm:exact", "kappa"] == pytest.approx(1.0)
    assert bool(table.loc["llm:exact", "eligible"]) is True
    assert bool(table.loc["llm:poor", "eligible"]) is False
    # always answering 1 agrees with the human by chance only: kappa 0, not eligible
    assert bool(table.loc["llm:constant", "eligible"]) is False
    assert table.loc["llm:constant", "kappa"] == pytest.approx(0.0)
    assert result.n_common == len(keys) and result.n_queries == 24


def test_compare_kappas_match_scikit_learn_on_the_common_pairs(compared):
    keys, grades, human, models = compared
    result = compare_labellers(human, models, n_boot=100, seed=0)
    row = result.table.set_index("model").loc["llm:close"]
    y_human = [grades[k] for k in keys]
    y_model = [q.grade for q in models["llm:close"]]
    assert row["kappa"] == pytest.approx(
        cohen_kappa_score(y_human, y_model, weights="quadratic")
    )
    assert row["kappa_ge1"] == pytest.approx(
        cohen_kappa_score([g >= 1 for g in y_human], [g >= 1 for g in y_model])
    )
    assert row["kappa_ge2"] == pytest.approx(
        cohen_kappa_score([g >= 2 for g in y_human], [g >= 2 for g in y_model])
    )
    assert row["kappa_low"] < row["kappa"] < row["kappa_high"]


def test_shortlist_keeps_models_within_noise_of_the_best_fastest_first(compared):
    _, _, human, models = compared
    result = compare_labellers(human, models, n_boot=400, seed=0)
    table = result.table.set_index("model")

    # two exact models tie: both shortlisted, the 1 s one before the 3 s one
    assert result.shortlist[:2] == ["llm:exact-fast", "llm:exact"]
    assert bool(table.loc["llm:poor", "shortlisted"]) is False
    assert table.loc["llm:exact", "delta_kappa"] == pytest.approx(0.0)
    # eligible but clearly worse than the best is not shortlisted
    assert table.loc["llm:close", "delta_high"] < 0 or bool(
        table.loc["llm:close", "shortlisted"]
    )


def test_a_model_far_below_the_best_is_not_shortlisted_even_if_it_passes_the_bar():
    keys, grades, human = human_world(n_queries=40, per_query=6, seed=3)
    models = {
        "llm:exact": model_qrels("llm:exact", keys, grades, lambda g, i: g),
        "llm:ok": model_qrels("llm:ok", keys, grades, noisy(0.2, seed=4)),
    }
    result = compare_labellers(human, models, n_boot=500, seed=0, bar=(0.5, 0.4))
    row = result.table.set_index("model").loc["llm:ok"]
    assert bool(row["eligible"]) is True  # passes a lowered bar...
    assert row["delta_high"] < 0  # ...but is worse than the best beyond noise
    assert bool(row["shortlisted"]) is False
    assert result.shortlist == ["llm:exact"]


def test_compare_uses_only_pairs_every_model_labelled_and_reports_coverage(compared):
    keys, grades, human, models = compared
    models = dict(models)
    models["llm:partial"] = models["llm:exact"][: len(keys) // 2]  # labelled half
    failures = {
        "llm:partial": [
            LabelFailure(
                query_id=q,
                doc_id=d,
                labeller="llm:partial",
                prompt_version="v1",
                text_sha256=sha,
                status="parse_error",
            )
            for q, d, sha in keys[len(keys) // 2 : len(keys) // 2 + 3]
        ]
    }
    result = compare_labellers(human, models, failures, n_boot=100, seed=0)
    row = result.table.set_index("model").loc["llm:partial"]
    assert result.n_common == len(keys) // 2
    assert row["coverage"] == pytest.approx(0.5)
    assert row["parse_errors"] == 3 and row["api_errors"] == 0
    assert result.table.set_index("model").loc["llm:exact", "coverage"] == 1.0


def test_compare_ignores_labels_made_on_another_text(compared):
    keys, grades, human, models = compared
    stale = [q.model_copy(update={"text_sha256": "other"}) for q in models["llm:exact"]]
    with pytest.raises(ValueError, match="every model"):
        compare_labellers(human, {"llm:stale": stale}, n_boot=10)


def test_compare_needs_human_labels():
    with pytest.raises(ValueError, match="no human labels"):
        compare_labellers([], {"llm:x": []})


def test_render_compare_states_the_bar_and_the_verdict(compared):
    _, _, human, models = compared
    text = render_compare(compare_labellers(human, models, n_boot=100, seed=0), 100)
    assert "kappa >= 0.6" in text and ">= 0.5" in text
    assert "Shortlist, fastest first" in text
    assert "`llm:exact-fast`" in text


def test_render_compare_refuses_to_pick_when_nobody_reaches_the_bar(compared):
    keys, grades, human, _ = compared
    models = {
        "llm:poor": model_qrels("llm:poor", keys, grades, noisy(0.9, seed=2)),
        "llm:constant": model_qrels("llm:constant", keys, grades, lambda g, i: 1),
    }
    result = compare_labellers(human, models, n_boot=100, seed=0)
    assert result.shortlist == []
    text = render_compare(result, 100)
    assert "No model reaches the bar" in text and "least bad" in text
