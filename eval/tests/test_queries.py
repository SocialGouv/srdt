import json

from retrieval_eval.queries import (
    append_audit,
    append_queries,
    append_records,
    load_questions_with_idcc,
    read_queries,
)
from retrieval_eval.sampling import length_bucket, query_id


def record(text: str, split: str, source: str = "prod") -> dict:
    return {
        "query_id": query_id(text),
        "text": text,
        "source": source,
        "idcc": None,
        "length_bucket": length_bucket(text),
        "theme": "autre",
        "split": split,
    }


def existing_queries(n: int = 20, dev: int = 5) -> list[dict]:
    return [
        record(
            f"question existante numéro {i} sur le contrat",
            "dev" if i < dev else "test",
        )
        for i in range(n)
    ]


def questions(n: int) -> list[tuple[str, str | None]]:
    return [
        (f"nouvelle question {i} sur le préavis de démission", "0016") for i in range(n)
    ]


def test_load_questions_pads_idcc_and_maps_empty_to_none(tmp_path):
    path = tmp_path / "q.json"
    path.write_text(
        json.dumps(
            [
                {"Question": '  "Bonjour ?"  ', "IDCC": "953"},
                {"Question": "Sans convention ?", "IDCC": ""},
                {"Question": "Autre", "IDCC": 1147},
            ]
        )
    )
    assert load_questions_with_idcc(path) == [
        ("Bonjour ?", "0953"),
        ("Sans convention ?", None),
        ("Autre", "1147"),
    ]


def test_append_leaves_existing_records_untouched_and_keeps_the_dev_share():
    existing = existing_queries(20, dev=5)  # 25% dev
    before = json.dumps(existing)
    result = append_queries(existing, questions(8), "idcc22", lambda t: t, seed=1)

    assert json.dumps(existing) == before
    assert len(result.queries) == 8
    assert {r["source"] for r in result.queries} == {"idcc22"}
    assert sum(r["split"] == "dev" for r in result.queries) == 2  # 25% of 8
    assert all(r["idcc"] == "0016" for r in result.queries)


def test_append_skips_ids_already_present_and_duplicates_within_the_file():
    existing = existing_queries()
    repeat = (existing[3]["text"], None)
    new = questions(2)
    result = append_queries(existing, [repeat, *new, new[0]], "idcc22", lambda t: t, 1)

    assert [r["text"] for r in result.queries] == [t for t, _ in new]
    assert result.skipped == [existing[3]["query_id"], query_id(new[0][0])]


def test_append_anonymises_before_hashing_and_audits_the_original():
    existing = existing_queries()
    raw = [("Je suis Jean Dupont, puis-je démissionner ?", None)]

    def anonymise(text: str) -> str:
        return text.replace("Jean Dupont", "PERSONNE")

    result = append_queries(existing, raw, "idcc22", anonymise, seed=1)

    (rec,) = result.queries
    assert "Dupont" not in rec["text"]
    assert rec["query_id"] == query_id(rec["text"])
    (audit,) = result.audit
    assert audit["original"] == raw[0][0]
    assert audit["changed"] is True


def test_append_flags_questions_close_to_an_existing_one():
    existing = existing_queries()
    close = existing[0]["text"] + " svp"
    result = append_queries(existing, [(close, None)], "idcc22", lambda t: t, seed=1)
    assert result.near_existing == [query_id(close)]


def test_append_records_does_not_rewrite_existing_lines(tmp_path):
    path = tmp_path / "queries.jsonl"
    existing = existing_queries(3, dev=1)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in existing))
    head = path.read_bytes()

    new = append_queries(existing, questions(2), "idcc22", lambda t: t, seed=1).queries
    append_records(path, new)

    assert path.read_bytes().startswith(head)
    assert read_queries(path) == existing + new


def test_append_audit_writes_the_header_once(tmp_path):
    path = tmp_path / ".local" / "audit.csv"
    row = {
        "query_id": "q_1",
        "original": "a",
        "anonymised": "a",
        "changed": False,
        "pii_flags": "",
    }
    append_audit(path, [row])
    append_audit(path, [row])
    lines = path.read_text().splitlines()
    assert lines[0].startswith("query_id,")
    assert sum(line.startswith("query_id,") for line in lines) == 1
    assert len(lines) == 3
