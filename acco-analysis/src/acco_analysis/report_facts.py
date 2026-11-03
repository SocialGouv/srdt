"""Counts for the report that `metrics.json` does not hold: they need the passages.

Two kinds, kept apart in the report's wording:
- the typology (a clause specific to heat, or heat as one case of a general clause)
  comes from the filter labels, over the agreements both models read as about heat;
- keyword counts (a regulation cited, the right to withdraw, telework for exceptional
  circumstances) are plain searches in the extracts, not codings.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from acco_analysis.corpus import Agreement

# the 2025 heat decree and the article of the Code du travail it created
DECREE = re.compile(r"2025-482|R\.? ?4463", re.IGNORECASE)
WITHDRAWAL = re.compile(r"droit de retrait|danger grave et imminent", re.IGNORECASE)
# NAF sections by division (the first two digits of the APE code)
NAF_SECTIONS = (
    (1, 3, "A"), (5, 9, "B"), (10, 33, "C"), (35, 35, "D"), (36, 39, "E"),
    (41, 43, "F"), (45, 47, "G"), (49, 53, "H"), (55, 56, "I"), (58, 63, "J"),
    (64, 66, "K"), (68, 68, "L"), (69, 75, "M"), (77, 82, "N"), (84, 84, "O"),
    (85, 85, "P"), (86, 88, "Q"), (90, 93, "R"), (94, 96, "S"), (97, 98, "T"),
    (99, 99, "U"),
)  # fmt: skip
LANDSCAPING_APE = "8130Z"  # services d'aménagement paysager
LANDSCAPING_IDCC = "7018"  # its collective agreement of branch
RECENT_FROM = 2025  # the recent agreements the report compares with other studies
# the trigger codes that make a scheme graded: a vigilance level or a temperature
GRADED = (
    "vigilance_yellow", "vigilance_orange", "vigilance_red", "vigilance_unspecified",
    "temperature_threshold",
)  # fmt: skip
# a collective stoppage is made up for afterwards
RECOVERY = re.compile(r"récupér|rattrap", re.IGNORECASE)
# telework as the answer to "exceptional circumstances" (article L. 1222-11)
EXCEPTIONAL = re.compile(
    r"1222-11|circonstances exceptionnelles|force majeure|épidémie|pollution"
    r"|pandémie|intempéries",
    re.IGNORECASE,
)


def _both(row: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    check = row.get("check")
    return (row["main"], check) if check else None


def heat_passages(
    coding: Iterable[Mapping[str, Any]], passages: Mapping[str, Mapping[str, Any]]
) -> dict[str, list[Mapping[str, Any]]]:
    """Per agreement id: its passages that both models read as about heat."""
    by_agreement: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in coding:
        sides = _both(row)
        if sides and all(s.get("about_heat") for s in sides):
            by_agreement[row["agreement_id"]].append(passages[row["id"]])
    return by_agreement


def typology(
    by_agreement: Mapping[str, Sequence[Mapping[str, Any]]],
    relevance: Mapping[str, Mapping[str, Any]],
) -> tuple[int, int]:
    """(agreements with a clause specific to heat, agreements with only generic)."""
    specific = sum(
        1
        for ps in by_agreement.values()
        if any(relevance[p["id"]]["label"] == "specific" for p in ps)
    )
    return specific, len(by_agreement) - specific


def keyword_agreements(
    by_agreement: Mapping[str, Sequence[Mapping[str, Any]]], pattern: re.Pattern[str]
) -> int:
    return sum(
        1 for ps in by_agreement.values() if any(pattern.search(p["text"]) for p in ps)
    )


def telework_agreements(
    coding: Iterable[Mapping[str, Any]], passages: Mapping[str, Mapping[str, Any]]
) -> tuple[int, int]:
    """(agreements both models place in telework, of which the telework passage names
    exceptional circumstances: epidemic, pollution, strike, bad weather...)."""
    texts: dict[str, list[str]] = defaultdict(list)
    for row in coding:
        sides = _both(row)
        if sides and all("telework" in s.get("families", []) for s in sides):
            texts[row["agreement_id"]].append(passages[row["id"]]["text"])
    exceptional = sum(
        1 for ts in texts.values() if any(EXCEPTIONAL.search(t) for t in ts)
    )
    return len(texts), exceptional


def measure_agreements(
    coding: Iterable[Mapping[str, Any]],
    passages: Mapping[str, Mapping[str, Any]],
    code: str,
    pattern: re.Pattern[str],
) -> tuple[int, int]:
    """(agreements both models code with the measure, of which a passage of that
    measure matches the pattern)."""
    texts: dict[str, list[str]] = defaultdict(list)
    for row in coding:
        sides = _both(row)
        if sides and all(
            any(m["code"] == code for m in s.get("measures", [])) for s in sides
        ):
            texts[row["agreement_id"]].append(passages[row["id"]]["text"])
    matching = sum(1 for ts in texts.values() if any(pattern.search(t) for t in ts))
    return len(texts), matching


def measure_by_label(
    coding: Iterable[Mapping[str, Any]],
    relevance: Mapping[str, Mapping[str, Any]],
    code: str,
    label: str,
) -> int:
    """Agreements where both models code the measure in a heat passage that the filter
    labelled `label` ("specific" or "generic")."""
    agreements = set()
    for row in coding:
        sides = _both(row)
        if (
            sides
            and all(s.get("about_heat") for s in sides)
            and relevance[row["id"]]["label"] == label
            and all(
                any(m["code"] == code for m in s.get("measures", [])) for s in sides
            )
        ):
            agreements.add(row["agreement_id"])
    return len(agreements)


def naf_section(ape: str | None) -> str | None:
    """The NAF section letter of an APE code, None when there is no usable code."""
    if not ape or not ape[:2].isdigit():
        return None
    division = int(ape[:2])
    return next((s for low, high, s in NAF_SECTIONS if low <= division <= high), None)


def dedicated_agreements(
    by_agreement: Mapping[str, Sequence[Mapping[str, Any]]],
    relevance: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    """Agreements with at least one clause specific to heat."""
    return {
        a
        for a, ps in by_agreement.items()
        if any(relevance[p["id"]]["label"] == "specific" for p in ps)
    }


def sector_facts(
    agreements: Mapping[str, Agreement],
    profiles: Mapping[str, Mapping[str, Any]],
    heat: Iterable[str],
    dedicated: set[str],
) -> dict[str, int]:
    """Counts by broad sector (NAF section) over the agreements with a heat clause, from
    the strict profiles: industry (C), administrative and support services (N), public
    administration (O), transport (H), construction (F), and landscaping (APE 8130Z)."""
    ids = [a for a in heat if a in agreements]
    section = {a: naf_section(agreements[a].ape) for a in ids}

    def count(sector: str, pred=lambda a: True) -> int:
        return sum(1 for a in ids if section[a] == sector and pred(a))

    def measure(code: str, pred=lambda a: True) -> int:
        return sum(1 for a in ids if code in profiles[a]["measures"] and pred(a))

    landscaping = [a for a in ids if agreements[a].ape == LANDSCAPING_APE]
    facts = {f"sec_{s.lower()}": count(s) for s in "CNOHF"}
    facts |= {
        f"sec_{s.lower()}_dedicated": count(s, dedicated.__contains__) for s in "CHFO"
    }
    facts |= {
        "sec_o_telework": count("O", lambda a: "telework" in profiles[a]["families"]),
        "prime_total": measure("prime"),
        "prime_c": measure("prime", lambda a: section[a] == "C"),
        "rest_total": measure("rest_derogation"),
        "rest_c": measure("rest_derogation", lambda a: section[a] == "C"),
        "same_day_total": measure("same_day_change"),
        "collective_total": measure("collective_stoppage"),
        "land": len(landscaping),
        "land_idcc": sum(
            1 for a in landscaping if agreements[a].idcc == LANDSCAPING_IDCC
        ),
        "land_template": sum(1 for a in landscaping if profiles[a].get("template")),
        "land_same_day": sum(
            1 for a in landscaping if "same_day_change" in profiles[a]["measures"]
        ),
        "land_collective": sum(
            1 for a in landscaping if "collective_stoppage" in profiles[a]["measures"]
        ),
        "no_ape": sum(1 for a in ids if section[a] is None),
    }
    return facts


def _as_list(value: Any) -> list[str]:
    return value if isinstance(value, list) else [value]


def _year(agreement: Agreement) -> int:
    return int(agreement.signed[:4]) if agreement.signed else 0


def recent_facts(
    agreements: Mapping[str, Agreement],
    profiles: Mapping[str, Mapping[str, Any]],
    by_agreement: Mapping[str, Sequence[Mapping[str, Any]]],
    dedicated: set[str],
    since: int = RECENT_FROM,
) -> dict[str, int]:
    """Counts over the agreements signed from `since` on, to set beside other studies of
    recent agreements: all of those with a heat clause (`recent_*`) and those with a
    scheme specific to heat (`ded_*`). `profiles` are the strict and loose profiles."""
    strict = profiles["strict"]
    recent = [
        a for a in by_agreement if a in agreements and _year(agreements[a]) >= since
    ]
    ded = [a for a in recent if a in dedicated]

    def has(a: str, key: str, codes: Sequence[str]) -> bool:
        return any(c in _as_list(strict[a][key]) for c in codes)

    def counts(ids: list[str], prefix: str) -> dict[str, int]:
        return {
            f"{prefix}_schedule": sum(
                has(a, "measures", ("schedule_shift",)) for a in ids
            ),
            f"{prefix}_cooling": sum(has(a, "measures", ("cooling",)) for a in ids),
            f"{prefix}_telework": sum(has(a, "measures", ("telework",)) for a in ids),
            f"{prefix}_graded": sum(has(a, "triggers", GRADED) for a in ids),
            f"{prefix}_pay_maintained": sum(
                has(a, "pay", ("maintained",)) for a in ids
            ),
        }

    heat_companies = {
        (agreements[a].siret or "")[:9] or agreements[a].company
        for a in by_agreement
        if a in agreements
    }
    return (
        counts(recent, "recent")
        | counts(ded, "ded")
        | {
            "recent_n": len(recent),
            "ded_n": len(ded),
            "recent_pay_unspecified": sum(
                has(a, "pay", ("unspecified",)) for a in recent
            ),
            "recent_decree": keyword_agreements(
                {a: by_agreement[a] for a in recent}, DECREE
            ),
            "recent_collected": sum(
                1 for g in agreements.values() if _year(g) >= since
            ),
            "recent_heat_loose": sum(
                1
                for a in profiles["loose"]
                if a in agreements and _year(agreements[a]) >= since
            ),
            "companies": len(heat_companies),
        }
    )


def compute(
    coding: Sequence[Mapping[str, Any]],
    passages: Mapping[str, Mapping[str, Any]],
    relevance: Mapping[str, Mapping[str, Any]],
    agreements: Mapping[str, Agreement],
    profiles: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, int]:
    """Counts for the report. `profiles` are the profiles by mode (strict, loose) and
    agreement id."""
    by_agreement = heat_passages(coding, passages)
    specific, generic_only = typology(by_agreement, relevance)
    telework, exceptional = telework_agreements(coding, passages)
    stoppage, stoppage_recovery = measure_agreements(
        coding, passages, "collective_stoppage", RECOVERY
    )
    dedicated = dedicated_agreements(by_agreement, relevance)
    return (
        sector_facts(agreements, profiles["strict"], by_agreement, dedicated)
        | recent_facts(agreements, profiles, by_agreement, dedicated)
        | {
            "with_heat": len(by_agreement),
            "specific": specific,
            "generic_only": generic_only,
            "decree": keyword_agreements(by_agreement, DECREE),
            "withdrawal": keyword_agreements(by_agreement, WITHDRAWAL),
            "specific_schedule": measure_by_label(
                coding, relevance, "schedule_shift", "specific"
            ),
            "generic_telework": measure_by_label(
                coding, relevance, "telework", "generic"
            ),
            "generic_same_day": measure_by_label(
                coding, relevance, "same_day_change", "generic"
            ),
            "collective_stoppage": stoppage,
            "collective_stoppage_recovery": stoppage_recovery,
            "telework": telework,
            "telework_exceptional": exceptional,
        }
    )
