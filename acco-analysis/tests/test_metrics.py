import numpy as np
from test_rollup import coded, row

from acco_analysis.corpus import Agreement
from acco_analysis.metrics import (
    MIN_CELL,
    _single_number,
    breakdown,
    build,
    cooccurrence,
    wilson,
)
from acco_analysis.rollup import MODES, agreement_profiles


def test_wilson_on_known_values():
    assert wilson(0, 10) == (0.0, 0.2775)
    assert wilson(10, 10) == (0.7225, 1.0)
    assert wilson(5, 10) == (0.2366, 0.7634)
    assert wilson(0, 0) is None


def test_single_number_does_not_guess():
    assert _single_number("30") == 30
    assert _single_number("30 °C") == 30
    assert _single_number("7,5") == 7.5
    assert _single_number("10-15") is None
    assert _single_number("6h30") is None
    assert _single_number("mi juin") is None


def agreement(i: str, signed: str, sector: str = "S") -> Agreement:
    return Agreement(
        id=i,
        title="",
        company=i,
        siret=None,
        sector=sector,
        idcc=None,
        nature="ACCORD",
        signed=signed,
    )


def sample():
    rows = [
        row(
            "a-1",
            "a",
            coded(("water",), ("vigilance_red",)),
            coded(("water",), ("vigilance_red",)),
        ),
        row("b-1", "b", coded(("water", "cooling")), coded(("water",))),
        row("c-1", "c", coded(("telework",)), coded(("telework",))),
        row("d-1", "d", coded(heat=False), coded(heat=False)),
    ]
    agreements = [
        agreement("a", "2020-05-01"),
        agreement("b", "2020-06-01"),
        agreement("c", "2021-01-01"),
        agreement("d", "2021-02-01"),
        agreement("e", "2021-03-01"),  # collected, no kept passage
    ]
    profiles = {m: agreement_profiles(rows, m) for m in MODES}
    return rows, agreements, profiles


def test_cooccurrence_counts_agreements_jaccard_and_lift():
    _, _, profiles = sample()
    pairs = cooccurrence(profiles, "measures", "measures", 3)
    # cooling is too rare to be listed (below MIN_PAIR); with the limit lowered the
    # pair water+cooling would be 1 agreement
    assert pairs == []
    from acco_analysis import metrics

    old = metrics.MIN_PAIR
    metrics.MIN_PAIR = 1
    try:
        pairs = cooccurrence(profiles, "measures", "measures", 3)
    finally:
        metrics.MIN_PAIR = old
    assert len(pairs) == 1
    p = pairs[0]
    assert (p["a"], p["b"]) == ("cooling", "water")
    assert (p["strict"], p["loose"]) == (0, 1)
    assert p["jaccard"] == 0.5  # 1 / (1 + 2 - 1)
    assert p["lift"] == 1.5  # 1 * 3 / (1 * 2)


def test_breakdown_hides_percentages_in_small_groups():
    _, _, profiles = sample()
    out = breakdown(profiles, {"2020": ["a", "b"]}, {"measures": ["water"]})
    cell = out["2020"]["items"]["measures"]["water"]
    assert (cell["strict"], cell["loose"]) == (2, 2)
    assert out["2020"]["collected"] == 2 < MIN_CELL
    assert cell["share_loose"] is None


def test_build_end_to_end_on_a_small_corpus():
    rows, agreements, profiles = sample()
    result = build(
        snapshot_id="s",
        agreements=agreements,
        rows=rows,
        profiles=profiles,
        template_of={},
        clusters={"a-1": 0, "b-1": 0, "c-1": 1, "d-1": 1},
        relevance={"specific": 3, "generic": 1},
    )
    assert result["problems"] == []
    d = result["dataset"]
    assert d["collected"] == 5 and d["with_heat_clause_loose"] == 3
    assert d["without_heat_clause"] == 2
    water = result["dimensions"]["measures"]["water"]
    assert (water["strict"], water["loose"]) == (2, 2)
    assert water["share_loose"] == round(2 / 3, 4)
    assert water["share_collected_loose"] == round(2 / 5, 4)
    assert result["dimensions"]["measures"]["cooling"]["strict"] == 0
    assert result["families"]["telework"]["loose"] == 1
    assert result["by_year"]["2021"]["collected"] == 3
    assert result["by_year"]["2021"]["with_heat_loose"] == 1
    assert result["clusters"]["0"]["heat"] == 2
    assert np.isclose(sum(c["passages"] for c in result["clusters"].values()), 4)
