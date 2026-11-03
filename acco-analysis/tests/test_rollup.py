from typing import Any

import numpy as np

from acco_analysis.rollup import (
    DISAGREE,
    agreement_profiles,
    consensus,
    template_groups,
)


def coded(
    measures: tuple[str, ...] = (),
    triggers: tuple[str, ...] = (),
    heat: bool = True,
    initiative: str | None = "employer",
) -> dict[str, Any]:
    return {
        "measures": [{"code": c, "quote": "q", "verified": True} for c in measures],
        "triggers": list(triggers),
        "scope": [],
        "procedure": [],
        "initiative": initiative,
        "pay": "unspecified",
        "strength": "permission",
        "numbers": [],
        "about_heat": heat,
    }


def row(i: str, agreement: str, main: dict[str, Any], check: dict[str, Any]):
    return {"id": i, "agreement_id": agreement, "main": main, "check": check}


def test_consensus_strict_keeps_what_both_gave_loose_what_either_gave():
    r = row(
        "p",
        "a",
        coded(("water", "cooling"), initiative="employer"),
        coded(("water", "telework"), initiative="employee"),
    )
    strict, loose = consensus(r, "strict"), consensus(r, "loose")
    assert strict["measures"] == {"water"}
    assert loose["measures"] == {"water", "cooling", "telework"}
    assert strict["initiative"] == DISAGREE == loose["initiative"]
    assert strict["families"] == ["prevention"]
    assert sorted(loose["families"]) == ["prevention", "telework"]


def test_consensus_about_heat_needs_both_for_strict_one_for_loose():
    r = row("p", "a", coded(heat=True), coded(heat=False))
    assert not consensus(r, "strict")["about_heat"]
    assert consensus(r, "loose")["about_heat"]


def test_an_agreement_with_three_passages_is_one_profile():
    rows = [
        row("a-1", "a", coded(("water",)), coded(("water",))),
        row("a-2", "a", coded(("telework",)), coded(("telework",))),
        row("a-3", "a", coded(("cooling",), heat=False), coded(heat=False)),
        row("b-1", "b", coded(heat=False), coded(heat=False)),
    ]
    profiles = agreement_profiles(rows, "loose")
    assert set(profiles) == {"a"}  # b has no passage about heat
    p = profiles["a"]
    assert p["measures"] == ["telework", "water"]  # the passage not about heat is out
    assert p["passages"] == 2 and p["passages_total"] == 3
    assert p["families"] == ["prevention", "telework"]


def test_profile_template_is_the_group_of_most_of_its_passages():
    rows = [
        row("a-1", "a", coded(("water",)), coded(("water",))),
        row("a-2", "a", coded(("water",)), coded(("water",))),
    ]
    profiles = agreement_profiles(rows, "loose", {"a-1": 4, "a-2": 4})
    assert profiles["a"]["template"] == 4
    assert agreement_profiles(rows, "loose")["a"]["template"] is None


def test_template_groups_identical_text_in_two_agreements():
    ids = ["a-1", "b-1", "c-1", "c-2"]
    agreements = ["a", "b", "c", "c"]
    texts = ["Même  texte.", "même texte.", "autre", "autre"]
    vectors = np.eye(4, dtype=np.float32)  # all different: only the text matches
    groups = template_groups(ids, agreements, texts, vectors)
    assert groups == {"a-1": 0, "b-1": 0}  # c repeats itself: not a template


def test_template_groups_near_duplicate_embeddings():
    ids = ["a-1", "b-1", "c-1"]
    vectors = np.array([[1, 0.02], [1, 0.0], [0, 1]], dtype=np.float32)
    groups = template_groups(ids, ["a", "b", "c"], ["x", "y", "z"], vectors)
    assert groups == {"a-1": 0, "b-1": 0}
