from typing import Any

from acco_analysis import report
from acco_analysis.corpus import Agreement
from acco_analysis.merge import check, merge_clusters

IDS = set(range(6))


def family(label: str, *clusters: Any) -> dict[str, Any]:
    return {"label": label, "summary": "s", "clusters": list(clusters)}


VALID = {
    "families": [
        family("A", 0, 1),
        family("B", 2, 3),
        family("C", 4),
        family("D", 5),
    ]
}


def test_a_valid_grouping_has_no_problem():
    families, problems = check(VALID, IDS)
    assert problems == [] and [f["clusters"] for f in families] == [
        [0, 1],
        [2, 3],
        [4],
        [5],
    ]


def test_problems_are_listed():
    answer = {
        "families": [
            family("A", 0, 1, 1),  # twice
            family("B", 2, 9),  # unknown
            family("C", 3),
            family("D", "4"),  # not a number
        ]
    }
    families, problems = check(answer, IDS)
    text = " ".join(problems)
    assert "le groupe 1 est dans plusieurs familles" in text
    assert "le groupe 9 n'existe pas" in text
    assert "'4'" in text
    assert "groupes sans famille : [4, 5]" in text
    # what is valid is kept
    assert [f["clusters"] for f in families] == [[0, 1], [2], [3]]


def test_wrong_number_of_families_is_a_problem():
    _, problems = check({"families": [family("all", *IDS)]}, IDS)
    assert any("1 familles" in p for p in problems)


def test_not_a_json_object():
    assert check("nope", IDS)[1]
    assert check({"families": []}, IDS)[1]


class FakeAlbert:
    def __init__(self, *answers: Any):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def chat_json(self, system: str, user: str, **_: Any) -> Any:
        self.prompts.append(user)
        return self.answers.pop(0)


def clusters() -> list[dict[str, Any]]:
    return [
        {
            "cluster": i,
            "label": f"L{i}",
            "summary": f"résumé {i}",
            "agreements": 10,
            "specific": 5,
            "generic": 1,
            "passages": 100 - i,
            "triggers": ["seuil"],
            "measures": [],
        }
        for i in range(6)
    ]


def test_merge_asks_once_when_the_grouping_is_valid():
    albert = FakeAlbert(VALID)
    result = merge_clusters(albert, clusters())  # type: ignore[arg-type]
    assert len(albert.prompts) == 1 and not result["retried"]
    assert (
        "### Groupe 3: L3" in albert.prompts[0]
        and "Déclencheurs : seuil" in albert.prompts[0]
    )
    # biggest family first
    assert result["families"][0]["clusters"] == [0, 1]


def test_merge_retries_with_the_problems_then_accepts():
    bad = {"families": [family("A", 0, 1), family("B", 2, 3, 4)]}
    albert = FakeAlbert(bad, VALID)
    result = merge_clusters(albert, clusters())  # type: ignore[arg-type]
    assert result["retried"] and result["unresolved"] == []
    assert "groupes sans famille : [5]" in albert.prompts[1]


def test_merge_repairs_what_is_still_wrong_after_the_retry():
    bad = {"families": [family("A", 0, 1), family("B", 2, 3), family("C", 4)]}
    result = merge_clusters(FakeAlbert(bad, bad), clusters())  # type: ignore[arg-type]
    assert result["unresolved"]  # reported, not hidden
    placed = sorted(i for f in result["families"] for i in f["clusters"])
    assert placed == [0, 1, 2, 3, 4, 5]
    # the cluster left out is a family of its own
    assert any(f["clusters"] == [5] and f["label"] == "L5" for f in result["families"])


def agreement(id: str, signed: str) -> Agreement:
    return Agreement(
        id=id,
        title="t",
        company=f"co {id}",
        siret=None,
        sector="Nettoyage",
        idcc="16",
        nature="ACCORD",
        signed=signed,
    )


def test_a_family_counts_an_agreement_once_across_its_groups():
    agreements = [agreement("A1", "2020-01-01"), agreement("A2", "2021-01-01")]
    passages = [
        {"id": "A1-0", "agreement_id": "A1"},
        {"id": "A1-1", "agreement_id": "A1"},  # same agreement, other group
        {"id": "A2-0", "agreement_id": "A2"},
    ]
    relevance = {p["id"]: {"label": "specific"} for p in passages}
    labels = {
        0: {"label": "x", "quotes": [{"id": "A1-0", "quote": "q0"}]},
        1: {"label": "y", "quotes": [{"id": "A1-1", "quote": "q1"}]},
    }
    result = report.build(
        snapshot_id="s",
        agreements=agreements,
        passages=passages,
        relevance=relevance,
        assignments={"A1-0": 0, "A1-1": 1, "A2-0": 1},
        labels=labels,
        meta={},
        families={"families": [family("F", 0, 1)], "retried": False, "unresolved": []},
    )
    (fam,) = result["families"]
    assert (fam["passages"], fam["agreements"]) == (3, 2)
    assert fam["share_of_agreements"] == 1.0
    assert fam["by_year"] == {"2020": 1, "2021": 1}
    assert [q["quote"] for q in fam["quotes"]] == ["q1", "q0"]  # biggest group first
    md = report.to_markdown(result)
    assert "## Families" in md and "### 1. F" in md and "Groups: 1, 2." in md
    assert "### 1. x" in md  # groups are nested under the families
