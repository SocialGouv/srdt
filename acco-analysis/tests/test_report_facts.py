from acco_analysis import report_facts
from acco_analysis.corpus import Agreement
from acco_analysis.report_facts import (
    DECREE,
    EXCEPTIONAL,
    RECOVERY,
    compute,
    heat_passages,
    keyword_agreements,
    measure_agreements,
    measure_by_label,
    naf_section,
    sector_facts,
    telework_agreements,
    typology,
)


def side(about_heat=True, families=(), measures=()):
    return {
        "about_heat": about_heat,
        "families": list(families),
        "measures": [{"code": m} for m in measures],
    }


def row(pid, agreement, main, check):
    return {"id": pid, "agreement_id": agreement, "main": main, "check": check}


def passage(pid, text):
    return {"id": pid, "agreement_id": pid.split("-")[0], "text": text}


def label(value):
    return {"label": value}


# a: specific + decree; b: generic only, telework for an epidemic; c: only one model
# reads it as heat (not counted); d: collective stoppage made up later
CODING = [
    row(
        "a-1", "a", side(measures=["schedule_shift"]), side(measures=["schedule_shift"])
    ),
    row("b-1", "b", side(families=["telework"]), side(families=["telework"])),
    row("c-1", "c", side(), side(about_heat=False)),
    row(
        "d-1",
        "d",
        side(measures=["collective_stoppage"]),
        side(measures=["collective_stoppage"]),
    ),
    row("d-2", "d", side(), None),
]
PASSAGES = {
    "a-1": passage(
        "a-1", "Conformément au décret n°2025-482 du 27 mai 2025, horaires d'été."
    ),
    "b-1": passage("b-1", "En cas de menace d'épidémie ou de canicule, télétravail."),
    "c-1": passage("c-1", "décret 2025-482"),
    "d-1": passage("d-1", "Les heures perdues seront récupérées."),
    "d-2": passage("d-2", "droit de retrait"),
}
RELEVANCE = {
    "a-1": label("specific"),
    "b-1": label("generic"),
    "c-1": label("specific"),
    "d-1": label("generic"),
    "d-2": label("specific"),
}


def test_heat_passages_need_both_models():
    by_agreement = heat_passages(CODING, PASSAGES)
    assert set(by_agreement) == {
        "a",
        "b",
        "d",
    }  # c: one model says no, d-2 has no check


def test_typology_splits_specific_from_generic_only():
    by_agreement = heat_passages(CODING, PASSAGES)
    assert typology(by_agreement, RELEVANCE) == (1, 2)


def test_keyword_agreements_count_agreements_not_passages():
    by_agreement = heat_passages(CODING, PASSAGES)
    assert keyword_agreements(by_agreement, DECREE) == 1  # c is not an agreement read
    assert keyword_agreements(by_agreement, EXCEPTIONAL) == 1


def test_telework_agreements_and_exceptional_wording():
    assert telework_agreements(CODING, PASSAGES) == (1, 1)


def test_measure_agreements_with_pattern():
    assert measure_agreements(CODING, PASSAGES, "collective_stoppage", RECOVERY) == (
        1,
        1,
    )
    assert measure_agreements(CODING, PASSAGES, "schedule_shift", RECOVERY) == (1, 0)


def agreement(i, ape, idcc=None):
    return Agreement(
        id=i, title="", company=i, siret=None, sector=None, idcc=idcc,
        nature="ACCORD", signed="2021-01-01", ape=ape,
    )  # fmt: skip


# a: industry (2849Z), dedicated; b: landscaping (8130Z, IDCC 7018) with a template;
# d: landscaping with a collective stoppage and no APE-independent template
AGREEMENTS = {
    "a": agreement("a", "2849Z"),
    "b": agreement("b", "8130Z", "7018"),
    "d": agreement("d", "8130Z"),
}


def profile(measures, families, template=None):
    return {"measures": measures, "families": families, "template": template}


PROFILES = {
    "a": profile(["schedule_shift", "prime"], ["hours"]),
    "b": profile(["same_day_change"], ["telework"], template=3),
    "d": profile(["collective_stoppage"], ["stoppage"]),
}


def test_naf_section_by_division():
    assert naf_section("2849Z") == "C" and naf_section("8130Z") == "N"
    assert naf_section("4322A") == "F" and naf_section("8430A") == "O"
    assert naf_section(None) is None and naf_section("ZZ") is None


def test_sector_facts_count_sectors_landscaping_and_shares_of_measures():
    facts = sector_facts(AGREEMENTS, PROFILES, ["a", "b", "d"], dedicated={"a"})
    assert (facts["sec_c"], facts["sec_n"], facts["sec_o"]) == (1, 2, 0)
    assert facts["sec_c_dedicated"] == 1 and facts["sec_h_dedicated"] == 0
    assert (facts["prime_total"], facts["prime_c"]) == (1, 1)
    assert (facts["land"], facts["land_idcc"], facts["land_template"]) == (2, 1, 1)
    assert (facts["land_same_day"], facts["same_day_total"]) == (1, 1)
    assert (facts["land_collective"], facts["collective_total"]) == (1, 1)
    assert facts["no_ape"] == 0
    # an agreement without usable APE code is counted apart
    no_code = AGREEMENTS | {"e": agreement("e", None)}
    assert (
        sector_facts(no_code, PROFILES | {"e": PROFILES["a"]}, ["a", "e"], set())[
            "no_ape"
        ]
        == 1
    )


def test_compute_keys_are_the_ones_the_report_reads():
    facts = compute(
        CODING, PASSAGES, RELEVANCE, AGREEMENTS, {"strict": PROFILES, "loose": PROFILES}
    )
    assert (
        facts["with_heat"] == 3
        and facts["specific"] == 1
        and facts["generic_only"] == 2
    )
    assert facts["decree"] == 1 and facts["withdrawal"] == 0
    assert facts["telework"] == 1 and facts["telework_exceptional"] == 1
    assert (
        facts["collective_stoppage"] == 1 and facts["collective_stoppage_recovery"] == 1
    )
    assert facts["sec_c"] == 1 and facts["land"] == 2  # the sector figures come along
    assert report_facts.WITHDRAWAL.search("le droit de retrait")


def test_measure_by_label_counts_agreements_per_kind_of_clause():
    assert measure_by_label(CODING, RELEVANCE, "schedule_shift", "specific") == 1
    assert measure_by_label(CODING, RELEVANCE, "schedule_shift", "generic") == 0
    assert measure_by_label(CODING, RELEVANCE, "collective_stoppage", "generic") == 1
