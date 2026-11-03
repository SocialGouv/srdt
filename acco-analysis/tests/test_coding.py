from typing import Any

from acco_analysis import coding
from acco_analysis.coding import _parse_open, family_of_clusters, sample_by_family

FAMILIES = {
    "families": [
        {"label": "Hours", "clusters": [0, 1]},
        {"label": "Telework", "clusters": [2]},
    ]
}


def passage(i: int) -> dict[str, Any]:
    return {"id": f"P{i}", "heading": "", "text": f"texte {i}"}


def test_family_of_clusters():
    assert family_of_clusters(FAMILIES) == {0: 0, 1: 0, 2: 1}


def test_sample_is_spread_over_the_clusters_of_a_family():
    passages = [passage(i) for i in range(60)]
    # cluster 0 is much larger than cluster 1
    assignments = {f"P{i}": 0 if i < 50 else 1 for i in range(60)}
    assignments["P59"] = 7  # in no family: ignored
    sample = sample_by_family(passages, assignments, FAMILIES, per_family=10)
    clusters = [assignments[p["id"]] for p in sample[0]]
    assert len(sample[0]) == 10 and clusters.count(1) == 5
    assert 1 not in sample  # no passage in the second family


def test_sample_takes_what_there_is_and_is_repeatable():
    passages = [passage(i) for i in range(4)]
    assignments = {"P0": 2, "P1": 2, "P2": 0, "P3": 1}
    first = sample_by_family(passages, assignments, FAMILIES, per_family=30)
    again = sample_by_family(passages, assignments, FAMILIES, per_family=30)
    assert {len(v) for v in first.values()} == {2}
    assert first == again


def test_a_quote_not_in_the_passage_is_dropped():
    text = "Les horaires sont décalés en cas de canicule."
    by_id = {"P1": {"id": "P1", "text": text}}
    answer = {
        "results": [
            {"id": "P1", "quote": "horaires sont décalés en cas de canicule"},
            {"id": "P2", "quote": "unknown passage"},
        ]
    }
    assert _parse_open(answer, by_id)["P1"]["quote"] == (
        "horaires sont décalés en cas de canicule"
    )
    assert "P2" not in _parse_open(answer, by_id)
    answer["results"][0]["quote"] = "horaires fixes toute l'année, jamais décalés"
    assert _parse_open(answer, by_id)["P1"]["quote"] is None


def test_families_are_views_over_the_measures():
    from acco_analysis.codebook import NO_FAMILY, families_of

    assert families_of({"schedule_shift", "prime"}) == ["hours", "pay"]
    assert families_of({"reference_only"}) == [NO_FAMILY]
    assert families_of(set()) == [NO_FAMILY]


def test_every_family_code_is_a_measure():
    from acco_analysis.codebook import FAMILIES, MEASURES

    for _, codes in FAMILIES.values():
        assert set(codes) <= set(MEASURES.values)


def test_closed_answer_is_checked_against_the_codebook_and_the_passage():
    from acco_analysis.coding import clean_closed

    text = "En cas de canicule, une pause de 10 minutes est accordée."
    item = {
        "id": "P1",
        "about_heat": "false",
        "measures": [
            {"code": "extra_breaks", "quote": "une pause de 10 minutes est accordée"},
            {"code": "prime", "quote": "une prime de 50 euros"},  # not in the text
            {"code": "teleportation", "quote": "x"},  # not in the codebook
        ],
        "triggers": ["canicule_unqualified", "full_moon"],
        "initiative": ["employer", "employee"],  # single-valued: first kept
        "pay": "unspecified",
        "numbers": [{"kind": "duration_minutes", "value": 10, "what": "pause"}],
    }
    out = clean_closed(item, text)
    assert [(m["code"], m["verified"]) for m in out["measures"]] == [
        ("extra_breaks", True),
        ("prime", False),
    ]
    assert out["unknown"] == {"measures": ["teleportation"], "triggers": ["full_moon"]}
    assert out["initiative"] == "employer" and out["about_heat"] is False
    assert out["numbers"][0]["value"] == "10"
    assert out["families"] == ["prevention", "pay"]


def test_a_short_quote_is_accepted_and_an_empty_one_is_not():
    from acco_analysis.coding import quote_in_text

    assert quote_in_text("pause de 10 minutes", "Une PAUSE de 10  minutes.")
    assert not quote_in_text("", "texte")
    assert not quote_in_text("abc", "abc def")


def test_kappa_and_reliability():
    from acco_analysis.coding import kappa, reliability

    assert kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    assert kappa([1, 1, 1], [1, 1, 1]) is None  # one value only: no chance baseline
    assert kappa([1, 0, 1, 0], [0, 1, 0, 1]) == -1.0

    def coded(codes: list[str], initiative: str) -> dict[str, Any]:
        return {
            "measures": [{"code": c} for c in codes],
            "triggers": [],
            "initiative": initiative,
            "scope": [],
            "pay": "unspecified",
            "procedure": [],
            "strength": "obligation",
        }

    main = {"a": coded(["water"], "employer"), "b": coded(["prime"], "employer")}
    check = {"a": coded(["water"], "employer"), "b": coded(["water"], "employee")}
    report = reliability(main, check, min_count=1)
    assert report["passages"] == 2
    assert report["measures"]["exact_match"] == 0.5
    assert report["measures"]["mean_jaccard"] == 0.5
    assert report["initiative"]["agreement"] == 0.5


def _coded(measures: list[str], pay: str = "unspecified") -> dict[str, Any]:
    from acco_analysis.codebook import families_of

    return {
        "measures": [{"code": c} for c in measures],
        "triggers": [],
        "initiative": "employer",
        "scope": [],
        "pay": pay,
        "procedure": [],
        "strength": "obligation",
        "families": families_of(set(measures)),
    }


def _row(i: str, main: list[str], check: list[str]) -> dict[str, Any]:
    return {
        "id": i,
        "agreement_id": "ACCO" + i,
        "main": _coded(main),
        "check": _coded(check),
    }


def test_queue_mixes_disagreements_and_agreements_across_groups():
    from acco_analysis.coding_labelling import queue_items

    rows = [_row(f"A{i}", ["water"], ["water"]) for i in range(6)]
    rows += [_row(f"B{i}", ["prime"], ["telework"]) for i in range(6)]
    rows += [_row(f"C{i}", ["water"], ["water"]) for i in range(6)]
    passages = {r["id"]: {"heading": "h", "text": "texte canicule"} for r in rows}
    groups = {r["id"]: 0 if r["id"][0] in "AB" else 1 for r in rows}
    items = queue_items(rows, passages, groups, size=8)
    assert len(items) == 8 and [i["order"] for i in items] == list(range(1, 9))
    first = {i["id"] for i in items[:4]}
    assert any(i.startswith("B") for i in first) and any(
        i.startswith("C") for i in first
    )
    assert items == queue_items(rows, passages, groups, size=8)  # repeatable


def test_page_embeds_the_data_and_survives_a_closing_script_tag():
    from acco_analysis.coding_labelling import render_page

    html = render_page(
        [{"id": "P", "order": 1, "heading": "h", "text": "a </script> b", "url": "u"}]
    )
    assert "__DATA__" not in html and "</script> b" not in html
    assert html.count("</script>") == 1


def test_evaluate_scores_each_model_against_the_hand_coding():
    from acco_analysis.coding_labelling import evaluate

    rows = [
        _row("1", ["water", "prime"], ["water"]),
        _row("2", ["telework"], ["telework"]),
    ]
    labels = {
        "1": {
            "measures": ["water"],
            "triggers": [],
            "initiative": "employer",
            "scope": [],
            "pay": "unspecified",
            "procedure": [],
            "strength": "obligation",
            "about_heat": True,
        },
        "2": {
            "measures": ["telework"],
            "triggers": [],
            "initiative": "employee",
            "scope": [],
            "pay": "unspecified",
            "procedure": [],
            "strength": "obligation",
            "about_heat": True,
        },
    }
    report = evaluate(rows, labels, min_count=1)
    assert report["passages"] == 2
    assert report["main"]["measures"]["precision"] == 0.667  # prime is extra
    assert report["main"]["measures"]["recall"] == 1.0
    assert report["check"]["measures"]["precision"] == 1.0
    assert report["main"]["initiative"]["accuracy"] == 0.5
    assert report["main"]["families_exact"] == 0.5  # passage 1 adds the pay family
    assert report["check"]["families_exact"] == 1.0


def test_sectioned_answer_is_merged_into_its_passage():
    by_id = {"A-1": {"id": "A-1"}}
    assert coding._owner({"id": "A-1_6-7"}, by_id) == "A-1"
    assert coding._owner({"id": "B-1"}, by_id) is None
    merged = coding._merge_items(
        [
            {"id": "A-1_6-6", "about_heat": False, "measures": []},
            {"id": "A-1_6-7", "about_heat": True, "measures": [{"code": "water"}]},
            {
                "id": "A-1_6-8",
                "about_heat": True,
                "measures": [{"code": "water"}, {"code": "cooling"}],
            },
        ]
    )
    assert [m["code"] for m in merged["measures"]] == ["water", "cooling"]
