import json
import random
from collections import Counter

import pytest

from retrieval_eval.queries import build_query_set, load_golden, write_queries
from retrieval_eval.sampling import (
    BUCKETS,
    allocate,
    assign_splits,
    build_candidates,
    clean_question,
    length_bucket,
    pii_flags,
    query_id,
    theme_of,
)

WORDS = "contrat salaire congé préavis prime horaire licenciement retraite".split()


def make_rows(count: int = 600, seed: int = 0) -> list[dict[str, str]]:
    rng = random.Random(seed)
    rows = []
    for i in range(count):
        size = rng.choice([2, 8, 40])  # words: keyword, short, detailed
        text = f"{i} " + " ".join(rng.choice(WORDS) for _ in range(size))
        rows.append(
            {
                "Question": text,
                "User ID": f"u{rng.randrange(40)}",
                "Department": "Nord",
                "Idcc": rng.choice(["", "0016"]),
            }
        )
    return rows


def run(rows, n=60, seed=1, golden=(), **kw):
    return build_query_set(rows, list(golden), lambda t: t, n=n, seed=seed, **kw)


def test_clean_question_strips_wrapping_quotes():
    assert clean_question('  "\n Bonjour ?\n"  ') == "Bonjour ?"
    assert clean_question('Il dit "non"') == 'Il dit "non"'


def test_length_bucket_edges():
    assert length_bucket("a" * 39) == "keyword"
    assert length_bucket("a" * 40) == "short"
    assert length_bucket("a" * 249) == "short"
    assert length_bucket("a" * 250) == "detailed"


def test_theme_ignores_accents_and_case():
    assert theme_of("Période d'ESSAI renouvelable") == "periode_essai"
    assert (
        theme_of("rupture conventionnelle et licenciement") == "rupture_conventionnelle"
    )
    assert theme_of("bonjour") == "autre"


def test_candidates_filters():
    rows = [
        {"Question": q, "User ID": "u", "Department": d, "Idcc": ""}
        for q, d in [
            ("Quelle est la durée du préavis ?", "Nord"),
            ("quelle est la  durée du préavis ?", "Oise"),  # duplicate
            ("court", "Nord"),
            ("x" * 2001, "Nord"),
            ("Test interne sur les congés payés", "Beta.gouv"),
            (
                "Actuellement en congé parental total, puis-je reprendre à mi-temps ?",
                "Nord",
            ),
        ]
    ]
    golden = ["Actuellement en congé parental total, puis-je reprendre à mi-temps ?!"]
    candidates, dropped = build_candidates(rows, golden)
    assert [c.text for c in candidates] == ["Quelle est la durée du préavis ?"]
    assert dropped == {
        "duplicate": 1,
        "too_short": 1,
        "too_long": 1,
        "test_department": 1,
        "near_golden": 1,
    }


def test_allocate_sums_to_n_and_respects_floor():
    quota = allocate({"keyword": 330, "short": 1613, "detailed": 594}, 120, floor=15)
    assert sum(quota.values()) == 120
    assert quota["keyword"] >= 15
    assert quota["short"] > quota["detailed"] > quota["keyword"]
    # floor lifts a tiny stratum, the others give up the difference
    quota = allocate({"keyword": 5, "short": 900, "detailed": 95}, 100, floor=15)
    assert quota["keyword"] == 5 and sum(quota.values()) == 100


def test_allocate_rejects_impossible_requests():
    with pytest.raises(ValueError):
        allocate({"a": 3, "b": 4}, 10, floor=1)


def test_sample_respects_size_and_user_cap():
    result = run(make_rows(), n=60, user_cap=2)
    prod = [r for r in result.queries if r["source"] == "prod"]
    assert len(prod) == 60
    users = Counter(
        r["User ID"]
        for r in make_rows()
        for p in prod
        if p["text"] == r["Question"].strip()
    )
    assert max(users.values()) <= 2
    assert {r["length_bucket"] for r in prod} == set(BUCKETS)


def test_same_seed_same_output_other_seed_differs():
    rows = make_rows()
    a, b = run(rows, seed=1), run(rows, seed=1)
    assert a.queries == b.queries
    assert [q["query_id"] for q in run(rows, seed=2).queries] != [
        q["query_id"] for q in a.queries
    ]


def test_dev_split_has_the_requested_size_and_every_bucket():
    result = run(
        make_rows(),
        n=61,
        golden=["Une question dorée ?", "Une autre ?"],
        dev_size=20,
    )
    splits = Counter(q["split"] for q in result.queries)
    assert splits == {"dev": 20, "test": len(result.queries) - 20}
    dev_buckets = Counter(
        q["length_bucket"] for q in result.queries if q["split"] == "dev"
    )
    assert set(dev_buckets) == set(BUCKETS)


def test_assign_splits_follows_bucket_proportions():
    buckets = {
        f"q{i}": BUCKETS[0 if i < 20 else 1 if i < 80 else 2] for i in range(100)
    }
    dev = Counter(
        buckets[q]
        for q, s in assign_splits(buckets, 3, dev_size=10).items()
        if s == "dev"
    )
    assert dev == {"keyword": 2, "short": 6, "detailed": 2}


def test_assign_splits_dev_larger_than_data():
    assert set(assign_splits({"q1": "short"}, 0, dev_size=60).values()) == {"dev"}


def test_golden_questions_are_seeded_and_never_sampled():
    golden = ["Quelle est la durée du préavis de licenciement en CDI ?"]
    rows = make_rows() + [
        {"Question": golden[0], "User ID": "u1", "Department": "Nord", "Idcc": ""}
    ]
    result = run(rows, golden=golden)
    assert [q["source"] for q in result.queries].count("judge18") == 1
    assert [q["text"] for q in result.queries].count(golden[0]) == 1


def test_only_anonymised_text_is_written(tmp_path):
    rows = make_rows(200)
    rows[0]["Question"] = "Madame Dupont chez Acme veut un préavis"
    result = build_query_set(
        rows,
        [],
        lambda t: t.replace("Dupont", "PERSONNE").replace("Acme", "ENTREPRISE"),
        n=200 - 1,
        seed=1,
        floor=1,
        user_cap=100,
    )
    out = tmp_path / "queries.jsonl"
    write_queries(out, result.queries, force=False)
    content = out.read_text()
    assert "Dupont" not in content and "Acme" not in content
    assert "PERSONNE" in content
    assert all("original" not in json.loads(line) for line in content.splitlines())
    audit = {a["query_id"]: a for a in result.audit}
    assert any("Dupont" in a["original"] for a in audit.values())


def test_write_queries_refuses_to_overwrite(tmp_path):
    out = tmp_path / "queries.jsonl"
    write_queries(out, [{"query_id": "q_1"}], force=False)
    with pytest.raises(FileExistsError):
        write_queries(out, [{"query_id": "q_2"}], force=False)
    write_queries(out, [{"query_id": "q_2"}], force=True)
    assert "q_2" in out.read_text()


def test_query_id_ignores_case_and_spacing():
    assert query_id("Bonjour  le monde") == query_id("bonjour le MONDE")


def test_pii_flags():
    assert pii_flags("appelez le 06 12 34 56 78") == ["digits"]
    assert "at_sign" in pii_flags("écrire à jean@exemple.fr")
    assert "title_name" in pii_flags("Monsieur Martin m'a licencié")
    assert pii_flags("Madame, Monsieur, bonjour") == []
    assert pii_flags("Quel préavis après 2 ans ?") == []


def test_load_golden_dedups(tmp_path):
    path = tmp_path / "g.json"
    path.write_text(
        json.dumps([{"question": "a"}, {"question": "a"}, {"question": "b"}])
    )
    assert load_golden(path) == ["a", "b"]
