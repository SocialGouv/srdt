"""The file-based commands, run on a small fake run. `pool` and a real `label` need
the network and are covered through their functions (test_pool, test_labeller)."""

import csv
import json
from pathlib import Path

import pytest
from conftest import ROOT

from retrieval_eval.cli import main
from retrieval_eval.data import (
    DocRecord,
    Qrel,
    Query,
    Ranking,
    load_qrels,
    text_sha256,
)
from retrieval_eval.jsonl import append_jsonl
from retrieval_eval.pool import DOCS_FILE, RANKINGS_FILE

MODEL = "albert/gpt-oss-120b"  # a name of config/models.toml
N_QUERIES = 12


@pytest.fixture
def world(tmp_path: Path):
    queries = [
        Query(
            query_id=f"q{i}",
            text=f"Question {i} sur le préavis ?",
            source="prod",
            idcc="1979" if i % 3 == 0 else None,
            length_bucket="short",
            split="dev" if i < 4 else "test",
        )
        for i in range(N_QUERIES)
    ]
    queries_path = tmp_path / "queries.jsonl"
    append_jsonl(queries_path, queries)

    run_dir = tmp_path / "runs" / "r1"
    docs = [
        DocRecord(
            doc_id=f"d{j}",
            title=f"Fiche {j}",
            url=f"https://x/{j}",
            source="information",
            text=f"texte {j}",
            text_sha256=text_sha256(f"texte {j}"),
        )
        for j in range(6)
    ]
    append_jsonl(run_dir / DOCS_FILE, docs)
    rankings = []
    for q in queries:
        rankings.append(
            Ranking(
                query_id=q.query_id,
                variant="knn",
                doc_ids=["d3", "d4", "d0", "d1", "d2", "d5"],
                scores=[None] * 6,
            )
        )
        rankings.append(
            Ranking(
                query_id=q.query_id,
                variant="hybrid+rerank",
                doc_ids=["d0", "d1", "d2", "d3", "d4", "d5"],
                scores=[None] * 6,
            )
        )
    append_jsonl(run_dir / RANKINGS_FILE, rankings)

    llm = []
    for q in queries:
        for j, doc in enumerate(docs):
            llm.append(
                Qrel(
                    query_id=q.query_id,
                    doc_id=doc.doc_id,
                    grade=2 if j == 0 else 1 if j == 1 else 0,
                    labeller=f"llm:{MODEL}",
                    prompt_version="v1",
                    text_sha256=doc.text_sha256,
                    rationale="parce que",
                )
            )
    llm_path = tmp_path / "qrels" / "llm.jsonl"
    append_jsonl(llm_path, llm)
    return dict(
        tmp=tmp_path, queries=queries_path, runs=tmp_path / "runs", llm=llm_path
    )


def cli(world, *args: str) -> int:
    command, rest = args[0], list(args[1:])
    queries = ["--queries", str(world["queries"])]
    runs = ["--runs-dir", str(world["runs"])]
    shared = {"agreement": [], "compare": runs}.get(command, queries + runs)
    return main([command, *shared, *rest])


def test_label_dry_run_reports_the_size_and_calls_nothing(world, capsys):
    code = cli(
        world,
        "label",
        "--run-id",
        "r1",
        "--model",
        MODEL,
        "--split",
        "all",
        "--dry-run",
    )
    out = capsys.readouterr().out
    assert code == 0
    # depth 10 over a 6-document ranking: the 6 documents of each of the 12 queries
    assert f"{N_QUERIES * 6} (query, document) pairs" in out
    assert "prompt tokens" in out


def test_label_refuses_a_run_above_the_cost_guard(world, capsys):
    code = cli(
        world,
        "label",
        "--run-id",
        "r1",
        "--model",
        MODEL,
        "--split",
        "all",
        "--max-pairs",
        "10",
    )
    assert code == 2
    assert "exceed --max-pairs 10" in capsys.readouterr().err


def test_label_rejects_an_unknown_model_and_a_missing_pool(world, capsys):
    assert cli(world, "label", "--run-id", "r1", "--model", "nope") == 2
    assert "unknown model" in capsys.readouterr().err
    assert cli(world, "label", "--run-id", "absent", "--model", MODEL) == 2
    assert "run `pool` first" in capsys.readouterr().err


def test_prompt_prints_the_exact_messages(world, capsys):
    code = cli(world, "prompt", "--run-id", "r1", "--query-id", "q0", "--doc-id", "d2")
    out = capsys.readouterr().out
    assert code == 0
    assert "--- system ---" in out and "--- user ---" in out
    assert "Question 0 sur le préavis ?" in out and "texte 2" in out
    assert "IDCC) : 1979" in out  # q0 has an idcc


def test_audit_round_trip_then_agreement_and_report(world, capsys):
    tmp = world["tmp"]
    sheet, key = tmp / "sheet.csv", tmp / "key.json"
    assert (
        cli(
            world,
            "audit-export",
            "--run-id",
            "r1",
            "--llm-qrels",
            str(world["llm"]),
            "--split",
            "all",
            "--n",
            "30",
            "--sheet",
            str(sheet),
            "--key",
            str(key),
        )
        == 0
    )
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    assert rows and "parce que" not in sheet.read_text(encoding="utf-8")

    keyed = {k["audit_id"]: k for k in json.loads(key.read_text())}
    for row in rows:  # a human who agrees with the LLM, except on every fourth row
        llm_grade = keyed[row["audit_id"]]["llm_grade"]
        row["grade"] = str(
            llm_grade if int(row["audit_id"][1:]) % 4 else (llm_grade + 1) % 3
        )
    with sheet.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    human = tmp / "qrels" / "human.jsonl"
    code = main(
        [
            "audit-import",
            "--sheet",
            str(sheet),
            "--key",
            str(key),
            "--annotator",
            "Rémi",
            "--out",
            str(human),
        ]
    )
    assert code == 0 and human.exists()

    out_md = tmp / "agreement.md"
    assert (
        cli(
            world,
            "agreement",
            "--reference",
            str(human),
            "--other",
            str(world["llm"]),
            "--bootstrap",
            "100",
            "--out",
            str(out_md),
        )
        == 0
    )
    text = out_md.read_text(encoding="utf-8")
    assert "Agreement of llm:" in text and "human:Rémi" in text
    assert "kappa (quadratic weights)" in text

    assert (
        cli(
            world,
            "report",
            "--run-id",
            "r1",
            "--qrels",
            str(world["llm"]),
            "--bootstrap",
            "100",
        )
        == 0
    )
    run_dir = world["runs"] / "r1"
    for name in ("report.md", "metrics.csv", "pairwise.csv", "per_query.csv"):
        assert (run_dir / name).exists()
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "| hybrid+rerank |" in report and "| knn |" in report
    assert "## all (12 queries with labels)" in report


def test_report_needs_a_labeller_when_the_qrels_have_several(world, capsys):
    other = [
        q.model_copy(update={"labeller": "human:x"})
        for q in __import__("retrieval_eval.data", fromlist=["load_qrels"]).load_qrels(
            world["llm"]
        )
    ]
    both = world["tmp"] / "qrels" / "human.jsonl"
    append_jsonl(both, other)
    code = cli(
        world,
        "report",
        "--run-id",
        "r1",
        "--qrels",
        str(world["llm"]),
        str(both),
    )
    assert code == 2 and "choose one with --labeller" in capsys.readouterr().err


def test_report_ignores_labels_made_on_another_text_of_a_document(world, capsys):
    from retrieval_eval.data import load_docs

    docs = load_docs(world["runs"] / "r1" / DOCS_FILE)
    path = world["runs"] / "r1" / DOCS_FILE
    path.unlink()
    changed = [d.model_copy(update={"text_sha256": "new"}) for d in docs.values()]
    append_jsonl(path, changed)

    code = cli(world, "report", "--run-id", "r1", "--qrels", str(world["llm"]))
    assert code == 2  # every label is stale, so nothing is left to report on
    assert "nothing to report" in capsys.readouterr().err


def test_pool_without_a_key_is_a_one_line_error(world, capsys, monkeypatch):
    monkeypatch.setattr("retrieval_eval.cli.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("AUTH_API_KEY", raising=False)  # and not reloaded from .env
    assert cli(world, "pool", "--run-id", "r2") == 2
    assert "AUTH_API_KEY is not set" in capsys.readouterr().err


def test_the_default_candidates_file_has_the_model_used_here():
    from judge_eval.judge import load_models

    names = {m.name for m in load_models(ROOT / "config/labellers.toml")}
    assert MODEL in names


@pytest.mark.parametrize(
    "value, expected",
    [
        ("http://localhost:8000", "http://localhost:8000"),
        ("https://api.example.org/", "https://api.example.org"),
        ("https://api.example.org/api/v1", "https://api.example.org"),
        ("https://api.example.org/api/v1/", "https://api.example.org"),
    ],
)
def test_api_base_url_drops_the_suffix_the_client_adds(monkeypatch, value, expected):
    from retrieval_eval.cli import api_base_url

    monkeypatch.setenv("API_BASE_URL", value)
    assert api_base_url() == expected


# --- choosing the labeller ----------------------------------------------------


def sample(world, *args: str) -> int:
    return cli(world, "sample-pairs", "--run-id", "r1", *args)


def test_sample_pairs_needs_an_explicit_split(world, capsys):
    assert sample(world) == 2
    assert "--split is required" in capsys.readouterr().err


def test_sample_pairs_writes_a_blind_sheet_and_a_key_and_protects_them(world, capsys):
    sheet, key = world["tmp"] / "sheet.csv", world["tmp"] / "key.json"
    args = ["--split", "all", "--n", "20", "--sheet", str(sheet), "--key", str(key)]
    assert sample(world, *args) == 0
    assert "20 rows" in capsys.readouterr().out
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    assert len(rows) == 20 and all(r["grade"] == "" for r in rows)
    keyed = json.loads(key.read_text())
    assert len(keyed) == 20 and all(k["llm_grade"] is None for k in keyed)

    # the sheet may now hold hours of human labels: never overwrite silently
    sheet.write_text(sheet.read_text() + "marker")
    assert sample(world, *args) == 2
    assert "use --force" in capsys.readouterr().err
    assert sheet.read_text().endswith("marker")
    assert sample(world, *args, "--force") == 0


def test_sample_pairs_subset_gives_a_blind_second_pass(world, capsys):
    tmp = world["tmp"]
    sheet, key = tmp / "sheet.csv", tmp / "key.json"
    sample(
        world, "--split", "all", "--n", "20", "--sheet", str(sheet), "--key", str(key)
    )
    second_sheet, second_key = tmp / "s2.csv", tmp / "k2.json"
    code = sample(
        world,
        "--subset-of",
        str(key),
        "--n",
        "8",
        "--sheet",
        str(second_sheet),
        "--key",
        str(second_key),
    )
    assert code == 0
    first = {(k["query_id"], k["doc_id"]) for k in json.loads(key.read_text())}
    again = json.loads(second_key.read_text())
    assert len(again) == 8
    assert {(k["query_id"], k["doc_id"]) for k in again} <= first
    assert all(k["audit_id"].startswith("b") for k in again)


def test_label_from_a_key_counts_calls_for_every_model(world, capsys):
    tmp = world["tmp"]
    sheet, key = tmp / "sheet.csv", tmp / "key.json"
    sample(
        world, "--split", "all", "--n", "20", "--sheet", str(sheet), "--key", str(key)
    )
    capsys.readouterr()

    common = ["label", "--run-id", "r1", "--pairs", str(key), "--max-chars", "60000"]
    two_models = ["--model", MODEL, "--model", "albert/gemma-4-31b-it"]
    assert cli(world, *common, *two_models, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "20 (query, document) pairs from --pairs" in out
    assert "2 model(s): up to 40 calls" in out
    assert "documents cut at 60000 characters" in out
    assert out.count(".jsonl") == 2  # one qrels file per model, hash in the name

    # the guard counts pairs x models
    assert cli(world, *common, *two_models, "--max-pairs", "39") == 2
    assert "40 calls (20 pairs x 2 models) exceed --max-pairs 39" in (
        capsys.readouterr().err
    )
    assert cli(world, *common, *two_models, "--qrels", "x.jsonl") == 2
    assert "single --model" in capsys.readouterr().err


def test_label_names_the_qrels_file_after_the_prompt_hash(world, capsys):
    cli(
        world,
        "label",
        "--run-id",
        "r1",
        "--model",
        MODEL,
        "--split",
        "all",
        "--dry-run",
    )
    first = capsys.readouterr().out
    cli(
        world,
        "label",
        "--run-id",
        "r1",
        "--model",
        MODEL,
        "--split",
        "all",
        "--max-chars",
        "60000",
        "--dry-run",
    )
    second = capsys.readouterr().out
    name = [line for line in first.splitlines() if "->" in line][0]
    other = [line for line in second.splitlines() if "->" in line][0]
    assert name != other and "-v1-" in name


def test_label_rejects_pairs_with_limit_queries(world, capsys):
    key = world["tmp"] / "k.json"
    key.write_text("[]")
    code = cli(
        world,
        "label",
        "--run-id",
        "r1",
        "--model",
        MODEL,
        "--pairs",
        str(key),
        "--limit-queries",
        "3",
        "--dry-run",
    )
    assert code == 2 and "does not apply" in capsys.readouterr().err


def test_compare_end_to_end_through_the_cli(world, capsys):
    tmp = world["tmp"]
    qrels = load_qrels(world["llm"])
    human = [
        q.model_copy(update={"labeller": "human:r", "latency_s": None}) for q in qrels
    ]
    human_path = tmp / "qrels" / "human.jsonl"
    append_jsonl(human_path, human)
    good = tmp / "qrels" / "good.jsonl"
    append_jsonl(
        good,
        [
            q.model_copy(update={"labeller": "llm:good", "latency_s": 1.0})
            for q in qrels
        ],
    )
    flipped = tmp / "qrels" / "flipped.jsonl"
    append_jsonl(
        flipped,
        [
            q.model_copy(update={"labeller": "llm:flipped", "grade": 2 - q.grade})
            for q in qrels
        ],
    )
    code = cli(
        world,
        "compare",
        "--run-id",
        "r1",
        "--human",
        str(human_path),
        "--models-qrels",
        str(good),
        str(flipped),
        "--bootstrap",
        "100",
    )
    assert code == 0
    run_dir = world["runs"] / "r1"
    text = (run_dir / "compare.md").read_text(encoding="utf-8")
    assert "`llm:good`" in text and "llm:flipped" in text
    assert (run_dir / "compare.csv").exists()
    assert "Shortlist, fastest first: `llm:good`" in text


def test_compare_needs_a_human_labeller_when_there_are_several(world, capsys):
    tmp = world["tmp"]
    both = tmp / "qrels" / "both.jsonl"
    qrels = load_qrels(world["llm"])
    append_jsonl(
        both,
        [
            q.model_copy(update={"labeller": name})
            for q in qrels
            for name in ("human:a", "human:b")
        ],
    )
    code = cli(
        world,
        "compare",
        "--run-id",
        "r1",
        "--human",
        str(both),
        "--models-qrels",
        str(world["llm"]),
    )
    assert code == 2 and "--human-labeller" in capsys.readouterr().err


# --- screened sampling --------------------------------------------------------


@pytest.fixture
def screeners(world):
    """Two screeners over the whole pool: they agree on d0 (2) and d1 (1), disagree
    on d2, and grade d3-d5 zero."""
    base = load_qrels(world["llm"])
    a = [q.model_copy(update={"labeller": "llm:a"}) for q in base]
    b = [
        q.model_copy(
            update={"labeller": "llm:b", "grade": 1 if q.doc_id == "d2" else q.grade}
        )
        for q in base
    ]
    paths = [world["tmp"] / "qrels" / "a.jsonl", world["tmp"] / "qrels" / "b.jsonl"]
    append_jsonl(paths[0], a)
    append_jsonl(paths[1], b)
    return [str(p) for p in paths]


def test_sample_pairs_with_screeners_prints_the_strata_and_stores_weights(
    world, screeners, capsys
):
    tmp = world["tmp"]
    sheet, key = tmp / "s.csv", tmp / "k.json"
    code = sample(
        world,
        "--split",
        "all",
        "--screeners",
        *screeners,
        "--n",
        "12",
        "--sheet",
        str(sheet),
        "--key",
        str(key),
    )
    out = capsys.readouterr().out
    assert code == 0
    for name in (
        "consensus-relevant",
        "consensus-partial",
        "disputed",
        "consensus-irrelevant",
    ):
        assert name in out
    keyed = json.loads(key.read_text())
    assert len(keyed) == 12
    by_stratum = {}
    for item in keyed:
        by_stratum.setdefault(item["stratum"], []).append(item["weight"])
    # 12 queries x 1 pair (d0, d1, d2) and x 3 pairs (d3-d5) in the pool
    assert set(by_stratum) == {
        "consensus-relevant",
        "consensus-partial",
        "disputed",
        "consensus-irrelevant",
    }
    assert sum(sum(w) for w in by_stratum.values()) == pytest.approx(72)  # the pool
    # the human sheet carries neither strata nor weights
    assert "stratum" not in sheet.read_text() and "consensus" not in sheet.read_text()


def test_sample_pairs_allocation_overrides_the_default_shares(world, screeners, capsys):
    tmp = world["tmp"]
    code = sample(
        world,
        "--split",
        "all",
        "--screeners",
        *screeners,
        "--n",
        "99",
        "--allocation",
        "consensus-relevant=2,disputed=3",
        "--sheet",
        str(tmp / "s.csv"),
        "--key",
        str(tmp / "k.json"),
    )
    assert code == 0
    counts = {}
    for item in json.loads((tmp / "k.json").read_text()):
        counts[item["stratum"]] = counts.get(item["stratum"], 0) + 1
    assert counts == {"consensus-relevant": 2, "disputed": 3}

    bad = sample(
        world,
        "--split",
        "all",
        "--screeners",
        *screeners,
        "--allocation",
        "disputed",
        "--sheet",
        str(tmp / "x.csv"),
        "--key",
        str(tmp / "x.json"),
    )
    assert bad == 2 and "name=count" in capsys.readouterr().err


def test_compare_with_a_weighted_key_reports_pool_estimates(world, screeners, capsys):
    tmp = world["tmp"]
    key = tmp / "k.json"
    sample(
        world,
        "--split",
        "all",
        "--screeners",
        *screeners,
        "--n",
        "40",
        "--sheet",
        str(tmp / "s.csv"),
        "--key",
        str(key),
    )
    keyed = json.loads(key.read_text())
    pairs = {(k["query_id"], k["doc_id"], k["text_sha256"]) for k in keyed}
    truth = {
        (q.query_id, q.doc_id, q.text_sha256): q.grade for q in load_qrels(world["llm"])
    }
    # a human who agrees with the screeners, except on the disputed documents
    human = [
        Qrel(
            query_id=q,
            doc_id=d,
            grade=1 if d == "d2" else truth[(q, d, sha)],
            labeller="human:r",
            text_sha256=sha,
        )
        for q, d, sha in sorted(pairs)
    ]
    human_path = tmp / "qrels" / "human.jsonl"
    append_jsonl(human_path, human)
    code = cli(
        world,
        "compare",
        "--run-id",
        "r1",
        "--human",
        str(human_path),
        "--models-qrels",
        *screeners,
        "--key",
        str(key),
        "--bootstrap",
        "100",
    )
    assert code == 0
    text = (world["runs"] / "r1" / "compare.md").read_text(encoding="utf-8")
    assert "pool-weighted" in text and "| llm:a |" in text and "| llm:b |" in text
    assert "sample kappa" in text
