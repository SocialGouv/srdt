import csv

import pytest

from acco_analysis import labelling
from acco_analysis.label import verbatim
from acco_analysis.relevance import _parse, excerpt


def test_excerpt_is_centred_on_the_heat_term():
    text = "a" * 2000 + " canicule " + "b" * 2000
    out = excerpt(text, 600)
    assert "canicule" in out and out.startswith("…") and out.endswith("…")
    assert len(out) <= 602
    assert excerpt("court", 600) == "court"


def test_parse_keeps_only_known_ids_and_labels():
    answer = {
        "results": [
            {"id": "a", "label": "specific", "reason": "horaires"},
            {"id": "b", "label": "maybe"},
            {"id": "zzz", "label": "mention"},
            "junk",
        ]
    }
    assert _parse(answer, {"a", "b"}) == {
        "a": {"label": "specific", "reason": "horaires"}
    }
    assert _parse("not a dict", {"a"}) == {}


@pytest.mark.parametrize(
    ("quote", "ok"),
    [
        ("les horaires sont décalés", True),
        ("LES HORAIRES   SONT\nDÉCALÉS", True),
        ("« les horaires sont décalés … »", True),
        ("les horaires sont avancés", False),
        ("court", False),  # too short to prove anything
    ],
)
def test_verbatim(quote: str, ok: bool):
    text = "En cas de canicule, les horaires sont décalés d'une heure."
    assert verbatim(quote, text) is ok


def test_verbatim_ignores_the_unicode_form():
    assert verbatim("les horaires sont décalés", "les horaires sont décalés")


def passages(n: int) -> list[dict]:
    return [
        {"id": f"p{i}", "agreement_id": f"A{i}", "heading": "h", "text": f"texte {i}"}
        for i in range(n)
    ]


def relevance(n: int) -> dict[str, dict]:
    labels = ["specific", "generic", "mention"]
    return {
        f"p{i}": {
            "label": labels[i % 3],
            "check_label": labels[(i + (i % 7 == 0)) % 3],
            "agree": i % 7 != 0,
        }
        for i in range(n)
    }


def test_sample_takes_disagreements_first_then_spreads_the_labels():
    rows = labelling.make_sample(
        passages(300), relevance(300), size=60, disagreements=10
    )
    assert len(rows) == 60 and len({r["id"] for r in rows}) == 60
    assert sum(r["llm_label"] != r["check_label"] for r in rows) >= 10
    counts = {
        k: sum(r["llm_label"] == k for r in rows)
        for k in ("specific", "generic", "mention")
    }
    assert counts["specific"] >= 20 and counts["mention"] >= 15


def test_evaluate(tmp_path):
    rows = [
        {
            "id": "1",
            "human_label": "specific",
            "llm_label": "specific",
            "check_label": "mention",
        },
        {
            "id": "2",
            "human_label": "mention",
            "llm_label": "generic",
            "check_label": "mention",
        },
        {
            "id": "3",
            "human_label": "generic",
            "llm_label": "specific",
            "check_label": "generic",
        },
        {
            "id": "4",
            "human_label": "mention",
            "llm_label": "mention",
            "check_label": "mention",
        },
        {
            "id": "5",
            "human_label": "",
            "llm_label": "specific",
            "check_label": "specific",
        },
    ]
    report = labelling.evaluate(rows)
    assert (report["labelled"], report["of"]) == (4, 5)
    main = report["main"]
    # kept = specific or generic: 3 predicted, 2 right; 2 really kept, both found
    assert main["kept_precision"] == pytest.approx(0.667, abs=1e-3)
    assert main["kept_recall"] == 1.0
    assert main["accuracy_3_labels"] == 0.5
    assert report["check"]["kept_recall"] == 0.5

    file = tmp_path / "s.csv"
    labelling.write_csv(
        file, [{**r, "heading": "", "excerpt": "é", "url": ""} for r in rows]
    )
    assert list(csv.DictReader(open(file, encoding="utf-8-sig")))[0]["excerpt"] == "é"
    assert labelling.read_csv(file)[0]["id"] == "1"


def test_evaluate_needs_labels():
    with pytest.raises(ValueError, match="human_label"):
        labelling.evaluate(
            [{"human_label": "", "llm_label": "mention", "check_label": ""}]
        )


AGENDA = "\n".join(
    [
        "· Augmentation salaire 5 %",
        "· Congés d'ancienneté pour les cadres",
        "· Conditions de travail à l'atelier (chaleur)",
        "· Prime de productivité à revoir",
        "· Carte de lavage pour les vendeurs",
    ]
)
PROSE = (
    "En cas de canicule, les horaires de travail sont décalés d'une heure et des "
    "pauses supplémentaires sont accordées aux salariés exposés à la chaleur.\n"
    "L'employeur met à disposition de l'eau fraîche en quantité suffisante."
)


def test_looks_like_list():
    assert labelling.looks_like_list(AGENDA)
    assert labelling.looks_like_list(
        "Article 1 – Objet\t2\nArticle 2 – Durée\t3\nAnnexe"
    )
    assert not labelling.looks_like_list(PROSE)
    # a short passage is not a list, and a list of sentences is not one either
    assert not labelling.looks_like_list("Canicule : horaires adaptés.")
    assert not labelling.looks_like_list("")


def sample_rows() -> list[dict[str, str]]:
    """100 rows: 40 specific, 30 generic, 30 mention; every 4th is a disagreement,
    every 5th list-like."""
    rows = []
    for i in range(100):
        label = "specific" if i < 40 else "generic" if i < 70 else "mention"
        rows.append(
            {
                "id": f"p{i}",
                "llm_label": label,
                "check_label": "mention"
                if label != "mention" and i % 4 == 0
                else label,
                "list_like": "1" if i % 5 == 0 else "0",
                "human_label": "",
            }
        )
    return rows


def test_queue_order_prefixes_are_balanced():
    queue = labelling.queue_order(sample_rows())
    assert [r["order"] for r in queue] == [str(n) for n in range(1, 101)]
    assert len({r["id"] for r in queue}) == 100
    first = queue[:40]
    assert {r["llm_label"] for r in first} == {"specific", "generic", "mention"}
    for label, share in labelling.SHARE.items():
        n = sum(r["llm_label"] == label for r in first)
        assert abs(n - 40 * share) <= 2
    assert sum(r["llm_label"] != r["check_label"] for r in first) >= 8
    assert sum(r["list_like"] == "1" for r in first) >= 8
    # the same input gives the same queue, whatever the order of the rows
    assert queue == labelling.queue_order(sample_rows())
    assert queue == labelling.queue_order(sample_rows()[::-1])
    assert queue == labelling.queue_order(queue)


def test_queue_order_with_a_missing_label():
    rows = [r for r in sample_rows() if r["llm_label"] != "generic"]
    assert len(labelling.queue_order(rows)) == len(rows)


def test_import_labels_fills_the_sample():
    rows = [
        {"id": "a", "human_label": "", "note": ""},
        {"id": "b", "human_label": "", "note": ""},
        {"id": "c", "human_label": "specific", "note": "old"},
    ]
    out = labelling.import_labels(
        rows,
        [
            {"id": "a", "label": "mention", "note": "agenda"},
            {"id": "b", "label": "unsure"},
        ],
    )
    assert [(r["id"], r["human_label"], r["note"]) for r in out] == [
        ("a", "mention", "agenda"),
        ("b", "unsure", ""),
        ("c", "", ""),  # the page is the source of truth
    ]
    assert rows[0]["human_label"] == ""  # the input is left alone


def test_import_labels_refuses_what_does_not_match_the_sample():
    rows = [{"id": "a", "human_label": "", "note": ""}]
    with pytest.raises(ValueError, match="not in the sample"):
        labelling.import_labels(rows, [{"id": "zzz", "label": "mention"}])
    with pytest.raises(ValueError, match="unknown label"):
        labelling.import_labels(rows, [{"id": "a", "label": "maybe"}])


def test_evaluate_splits_lists_from_prose_and_skips_unsure():
    def row(h, m, c, kind):
        return {
            "id": f"{h}{m}{kind}",
            "human_label": h,
            "llm_label": m,
            "check_label": c,
            "list_like": kind,
        }

    rows = [
        row("mention", "specific", "mention", "1"),  # the list the filter overrates
        row("mention", "specific", "mention", "1"),
        row("specific", "specific", "specific", "0"),
        row("generic", "generic", "mention", "0"),
        row("unsure", "specific", "specific", "0"),
    ]
    report = labelling.evaluate(rows)
    assert (report["labelled"], report["unsure"], report["of"]) == (4, 1, 5)
    assert report["list_like"]["main"]["kept_precision"] == 0.0
    assert report["list_like"]["check"]["accuracy_3_labels"] == 1.0
    assert report["prose"]["main"]["kept_precision"] == 1.0
    assert report["main"]["kept_precision"] == pytest.approx(0.5)
