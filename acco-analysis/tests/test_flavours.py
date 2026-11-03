from typing import Any

import numpy as np

from acco_analysis.flavours import (
    COLOURED,
    describe,
    find_flavours,
    items_of,
    representatives,
    weight,
)
from acco_analysis.label import verbatim


def profile(**dims: list[str]) -> dict[str, Any]:
    base: dict[str, list[str]] = {"measures": [], "triggers": [], "pay": []}
    return {**base, **dims}


def test_items_skip_values_that_say_nothing_and_merge_vigilance_colours():
    p = profile(
        measures=["water", "other"],
        triggers=["vigilance_orange", "vigilance_red"],
        pay=["unspecified"],
    )
    assert items_of(p) == {"measures:water", f"triggers:{COLOURED}"}


def test_bare_canicule_gives_way_to_a_named_trigger():
    assert items_of(profile(triggers=["canicule_unqualified"])) == {
        "triggers:canicule_unqualified"
    }
    assert items_of(
        profile(triggers=["canicule_unqualified", "temperature_threshold"])
    ) == {"triggers:temperature_threshold"}


def test_named_triggers_and_pay_weigh_more():
    assert weight("triggers:fixed_period") == 2
    assert weight("pay:extra_pay") == 2
    assert weight("measures:water") == 1
    assert weight("triggers:canicule_unqualified") == 1


def members():
    out = {}
    for i in range(12):  # water + cooling
        out[f"a{i}"] = frozenset({"measures:water", "measures:cooling"})
    for i in range(12):  # water only
        out[f"b{i}"] = frozenset({"measures:water"})
    for i in range(12):  # telework
        out[f"d{i}"] = frozenset({"measures:telework"})
    for i in range(3):  # too few to be a flavour of their own
        out[f"c{i}"] = frozenset({"measures:water", "measures:telework"})
    return out


def test_flavours_are_specific_first_and_do_not_overlap():
    flavours, left, constant = find_flavours(members(), min_support=10)
    assert constant == []
    assert flavours[0][0] == ("measures:cooling", "measures:water")
    placed = [a for _, ids in flavours for a in ids]
    assert len(placed) == len(set(placed))
    assert set(left) == set(members()) - set(placed)
    # the three mixed agreements join the flavour that is frequent enough
    assert "c0" in placed


def test_flavours_leave_out_constant_items_and_rare_combinations():
    data = {
        f"a{i}": frozenset({"measures:telework", "pay:extra_pay"}) for i in range(20)
    }
    data |= {f"b{i}": frozenset({"measures:telework"}) for i in range(3)}
    flavours, left, constant = find_flavours(data, min_support=10)
    assert constant == ["measures:telework"]  # in all 23
    assert [f[0] for f in flavours] == [("pay:extra_pay",)]
    assert set(left) == {"b0", "b1", "b2"}


def test_representatives_show_a_shared_clause_once():
    vectors = np.array([[1, 0], [1, 0.01], [1, 0.02], [0, 1]], dtype=np.float32)
    units = ["t1", "t1", "t1", "a9"]  # the first three are the same template
    chosen = representatives([0, 1, 2, 3], vectors, units)
    assert len({units[i] for i in chosen}) == len(chosen)
    assert len(chosen) == 2


class FakeAlbert:
    def __init__(self, answer: dict[str, Any]):
        self.answer = answer

    def chat_json(self, system: str, user: str, *, max_tokens: int = 0):
        return self.answer


def test_describe_drops_quotes_that_are_not_in_the_passage():
    shown = [
        {
            "id": "p1",
            "heading": "h",
            "text": "En cas de canicule, les horaires sont décalés de deux heures.",
        }
    ]
    albert = FakeAlbert(
        {
            "name": " Horaires décalés ",
            "description": "d",
            "variations": ["v"],
            "quotes": [
                {"id": "p1", "quote": "les horaires sont décalés de deux heures"},
                {"id": "p1", "quote": "une phrase qui n'est pas dans le texte"},
                {"id": "other", "quote": "les horaires sont décalés de deux heures"},
            ],
        }
    )
    flavour = {
        "strict": 12,
        "family_strict": 40,
        "codes": [{"label": "x"}],
        "distributions": {},
    }
    out = describe(albert, flavour, "Horaires", shown)  # type: ignore[arg-type]
    assert out["name"] == "Horaires décalés"
    assert [q["id"] for q in out["quotes"]] == ["p1"]
    assert out["quotes_dropped"] == 2


class SequenceAlbert:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def chat_json(self, system: str, user: str, *, max_tokens: int = 0):
        self.calls += 1
        return self.answers.pop(0)


def test_describe_completes_to_three_quotes_from_the_passages():
    shown = [
        {
            "id": f"p{i}",
            "heading": "h",
            "text": f"Article {i}. En cas de canicule, l'employeur adapte les horaires",
        }
        for i in range(4)
    ]
    first = {
        "name": "n",
        "quotes": [{"id": "p0", "quote": "inventée, absente du texte"}],
    }
    retry = {
        "quotes": [{"id": "p1", "quote": "En cas de canicule, l'employeur adapte"}]
    }
    albert = SequenceAlbert(first, retry)
    flavour = {"strict": 12, "family_strict": 40, "codes": [], "distributions": {}}
    out = describe(albert, flavour, "Horaires", shown)  # type: ignore[arg-type]
    assert albert.calls == 2
    assert [q["id"] for q in out["quotes"]] == ["p1", "p0", "p2"]
    assert all(
        verbatim(q["quote"], s["text"])
        for q, s in zip(out["quotes"], [shown[1], shown[0], shown[2]], strict=True)
    )
