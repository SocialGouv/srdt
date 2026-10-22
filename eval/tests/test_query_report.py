"""The report on one question, and the questions production does worst on."""

import pytest
from test_retrieval_cli import cli, world  # noqa: F401  (a pytest fixture)

from retrieval_eval.data import DocRecord, Query, Ranking, text_sha256
from retrieval_eval.query_report import (
    find_queries,
    render_query_report,
    render_weaknesses,
    worst_queries,
)


def query(qid="q1", text="Mon employeur peut-il refuser mon congé ?", idcc=None):
    return Query(
        query_id=qid,
        text=text,
        source="prod",
        idcc=idcc,
        length_bucket="short",
        split="dev",
    )


def docs(n=15):
    return {
        f"d{i}": DocRecord(
            doc_id=f"d{i}",
            title=f"Fiche numéro {i}",
            source="information",
            text=f"texte {i}",
            text_sha256=text_sha256(f"texte {i}"),
        )
        for i in range(n)
    }


def rankings(qid="q1"):
    """Production returns d0..d11; hybrid puts d12 first; knn d13 first."""
    prod = [f"d{i}" for i in range(12)]
    hybrid = ["d12", *prod[:9], "d11", "d10"]
    knn = ["d13", "d12", *prod[:9]]
    return [
        Ranking(query_id=qid, variant=v, doc_ids=ids, scores=[None] * len(ids))
        for v, ids in (("hybrid+rerank", prod), ("hybrid", hybrid), ("knn", knn))
    ]


GRADES = {"d0": 2, "d1": 1, "d3": 0, "d11": 1, "d12": 2, "d13": 0, "d5": 0}
RATIONALES = {"d0": "répond à la question", "d12": "règle applicable"}


def test_the_report_shows_the_grades_the_ranks_and_what_was_missed():
    text = render_query_report(query(), rankings(), docs(), GRADES, RATIONALES)

    assert (
        "# Question q1" in text and "Mon employeur peut-il refuser mon congé ?" in text
    )
    assert "7 graded documents" in text and "2 graded 2, 2 graded 1, 3 graded 0" in text
    # production table: rank 1 is d0 graded 2, found at rank 2 of hybrid and 3 of knn
    row = next(
        line
        for line in text.splitlines()
        if "Fiche numéro 0" in line and line.startswith("| 1 ")
    )
    assert row.split("|")[2].strip() == "2"
    assert row.split("|")[-3].strip() == "2" and row.split("|")[-2].strip() == "3"
    # an ungraded document is shown as '?', not as 0
    assert any(
        "Fiche numéro 2" in line and "| ? |" in line for line in text.splitlines()
    )
    assert "1. **2** Fiche numéro 0: répond à la question" in text
    assert "(no rationale)" in text  # d1 has none
    # d11 (graded 1) is at production rank 12, outside the top 10; d12 is not there
    missed = text.split("## Useful documents production did not send")[1]
    assert "(2)" in missed.splitlines()[0]
    assert "Fiche numéro 12" in missed and "Fiche numéro 11" in missed
    d12 = next(line for line in missed.splitlines() if "Fiche numéro 12" in line)
    assert [c.strip() for c in d12.split("|")[-4:-1]] == ["-", "1", "2"]


def test_metrics_of_the_question_per_variant():
    text = render_query_report(query(), rankings(), docs(), GRADES, RATIONALES)
    table = text.split("## How each variant did on this question")[1]
    prod = next(
        line for line in table.splitlines() if line.startswith("| **hybrid+rerank**")
    )
    cells = [c.strip() for c in prod.split("|")[2:-1]]
    # useful docs: d0, d1, d11, d12. In production's top 10: d0, d1 -> precision 2/10
    assert cells[0] == "0.20" and cells[1] == "0.50"
    hybrid = next(line for line in table.splitlines() if line.startswith("| hybrid "))
    assert [c.strip() for c in hybrid.split("|")[2:4]] == ["0.30", "0.75"]


def test_human_grades_get_their_own_column():
    text = render_query_report(
        query(), rankings(), docs(), GRADES, RATIONALES, human={"d0": 1, "d1": 1}
    )
    assert "| # | grade | you | document |" in text
    row = next(line for line in text.splitlines() if line.startswith("| 1 |"))
    assert [c.strip() for c in row.split("|")[2:4]] == ["2", "1"]
    assert "`you` is the human grade" in text


def test_a_question_whose_useful_documents_are_all_in_the_top_ten():
    grades = {"d0": 2, "d1": 1}
    text = render_query_report(query(), rankings(), docs(), grades, {})
    assert "None: every document graded 1 or 2 is in its top 10." in text


def test_a_question_without_a_production_ranking_is_an_error():
    only_knn = [r for r in rankings() if r.variant == "knn"]
    with pytest.raises(ValueError, match="no hybrid\\+rerank ranking"):
        render_query_report(query(), only_knn, docs(), GRADES, {})


def test_find_queries_by_id_prefix_or_words_ignoring_accents():
    qs = [query("q_aaa", "Congé parental à temps partiel"), query("q_bbb", "Préavis")]
    assert [q.query_id for q in find_queries(qs, "q_a")] == ["q_aaa"]
    assert [q.query_id for q in find_queries(qs, "conge PARENTAL")] == ["q_aaa"]
    assert [q.query_id for q in find_queries(qs, "preavis")] == ["q_bbb"]
    assert find_queries(qs, "démission") == []


def test_worst_queries_ranks_by_production_ndcg_and_skips_empty_ones():
    def prod(qid, ids):
        return Ranking(
            query_id=qid, variant="hybrid+rerank", doc_ids=ids, scores=[None] * len(ids)
        )

    ranks = [
        prod("good", ["a", "b", "c"]),
        prod("bad", ["x", "y", "a"]),
        prod("none", ["a", "b"]),
        Ranking(query_id="bad", variant="knn", doc_ids=["a"], scores=[None]),
    ]
    grades = {
        "good": {"a": 2, "b": 1, "c": 0},
        "bad": {"a": 2, "x": 0, "y": 0},
        "none": {"a": 0, "b": 0},  # nothing useful: nothing can be missed
    }
    worst = worst_queries(ranks, grades, 5)
    assert [w.query_id for w in worst] == ["bad", "good"]
    assert worst[0].ndcg < worst[1].ndcg == pytest.approx(1.0)
    assert worst[0].relevant == 1
    text = render_weaknesses(
        worst, {"bad": query("bad", "Question difficile"), "good": query("good")}
    )
    assert "| bad |" in text and "Question difficile" in text


# --- command -----------------------------------------------------------------


@pytest.fixture
def labelled(world):  # noqa: F811
    from retrieval_eval.data import load_qrels
    from retrieval_eval.jsonl import append_jsonl

    path = world["tmp"] / "qrels" / "llm-check.jsonl"
    append_jsonl(path, load_qrels(world["llm"]))
    return dict(world, qrels=path)


def qr(labelled, *args: str) -> int:
    return cli(
        labelled,
        "query-report",
        "--run-id",
        "r1",
        "--qrels",
        str(labelled["qrels"]),
        *args,
    )


def test_command_shows_one_question(labelled, capsys):
    code = qr(labelled, "--query-id", "q3")
    out = capsys.readouterr().out
    assert code == 0 and "# Question q3" in out
    assert "Question 3 sur le préavis ?" in out
    assert "## What production sends to the answer step" in out


def test_command_finds_a_question_by_words_and_writes_the_file(labelled, tmp_path):
    target = tmp_path / "q.md"
    code = qr(labelled, "--search", "question 7", "--out", str(target))
    assert code == 0 and "# Question q7" in target.read_text(encoding="utf-8")


def test_an_ambiguous_search_lists_the_candidates(labelled, capsys):
    code = qr(labelled, "--search", "sur le préavis")
    err = capsys.readouterr().err
    assert code == 2 and "12 questions match" in err and "q0" in err


def test_unknown_question_and_missing_target_are_one_line_errors(labelled, capsys):
    assert qr(labelled, "--search", "introuvable") == 2
    assert "no question matches" in capsys.readouterr().err
    assert qr(labelled) == 2
    assert "--query-id, --search or --worst" in capsys.readouterr().err


def test_command_lists_the_worst_questions(labelled, capsys):
    code = qr(labelled, "--worst", "3")
    out = capsys.readouterr().out
    rows = [
        ln for ln in out.splitlines() if ln.startswith("| q") and "query id" not in ln
    ]
    assert code == 0 and "Lowest nDCG@10" in out and len(rows) == 3


def test_command_shows_the_human_grades_when_given(labelled, capsys):
    from retrieval_eval.data import load_qrels
    from retrieval_eval.jsonl import append_jsonl

    human = [
        q.model_copy(update={"labeller": "human:r"})
        for q in load_qrels(labelled["qrels"])
    ]
    path = labelled["tmp"] / "qrels" / "h.jsonl"
    append_jsonl(path, human)
    qr(labelled, "--query-id", "q1", "--human", str(path))
    assert "| # | grade | you | document |" in capsys.readouterr().out
