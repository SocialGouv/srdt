"""Counts and shares over the agreement profiles: how common each clause is, how the
dimensions split inside each family, by year / sector / IDCC, what goes together, and
which figures the models give.

Every figure has two readings (`strict`: both models, `loose`: either, see rollup.py).
Shares are over the agreements with a heat clause under the loose reading (`n_heat`)
and over the agreements collected; nothing here is a share of companies in general.
"""

import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from acco_analysis.codebook import DIMENSIONS, FAMILIES, NO_FAMILY, NUMBER_KINDS
from acco_analysis.corpus import Agreement
from acco_analysis.rollup import (
    DISAGREE,
    MODES,
    TRUNCATED_CHARS,
    consensus,
)

MIN_CELL = 10  # a group of fewer agreements gets its counts but no percentage
MODEL_DEPENDENT = 0.6  # strict / loose below this: the models disagree on the code
MIN_PAIR = 5
TOP_GROUPS = 15
LABELS: dict[str, dict[str, str]] = {
    d.name: {code: label for code, (label, _) in d.values.items()} for d in DIMENSIONS
}
LABELS["families"] = {name: label for name, (label, _) in FAMILIES.items()}
LABELS["families"][NO_FAMILY] = "Simple renvoi ou autre"
for _name in ("initiative", "pay", "strength"):
    LABELS[_name][DISAGREE] = "les deux modèles divergent"
    LABELS[_name]["unknown"] = "non renseigné"
DIMENSION_NAMES = [d.name for d in DIMENSIONS]
FAMILY_NAMES = [*FAMILIES, NO_FAMILY]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% interval of a share k/n; None when n is 0."""
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def _share(k: int, n: int, minimum: int = 0) -> float | None:
    return round(k / n, 4) if n and n >= minimum else None


def _unit(profile: dict[str, Any]) -> str:
    """What counts as one clause once templates are collapsed: the template group of the
    agreement, or the agreement itself."""
    t = profile["template"]
    return f"t{t}" if t is not None else profile["agreement_id"]


def _counts(
    profiles: dict[str, dict[str, Any]], dimension: str
) -> tuple[Counter[str], dict[str, set[str]]]:
    """(agreements per value, units per value) of one dimension."""
    agreements: Counter[str] = Counter()
    units: dict[str, set[str]] = defaultdict(set)
    for profile in profiles.values():
        for value in profile[dimension]:
            agreements[value] += 1
            units[value].add(_unit(profile))
    return agreements, units


def _cell(
    strict: int,
    loose: int,
    n_heat: int,
    n_collected: int,
) -> dict[str, Any]:
    return {
        "strict": strict,
        "loose": loose,
        "share_strict": _share(strict, n_heat),
        "share_loose": _share(loose, n_heat),
        "ci_strict": wilson(strict, n_heat),
        "ci_loose": wilson(loose, n_heat),
        "share_collected_strict": _share(strict, n_collected),
        "share_collected_loose": _share(loose, n_collected),
        "model_dependent": loose >= 10 and strict < MODEL_DEPENDENT * loose,
    }


def _listed(coded: dict[str, Any], dimension: str) -> list[str]:
    value = coded[dimension]
    return [value] if isinstance(value, str) else list(value)


def _values(dimension: str) -> list[str]:
    if dimension == "families":
        return FAMILY_NAMES
    d = next(d for d in DIMENSIONS if d.name == dimension)
    extra = [] if d.multi else [DISAGREE, "unknown"]
    return [*d.values, *extra]


def dimension_table(
    profiles: dict[str, dict[str, dict[str, Any]]],
    coded: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]],
    n_heat: int,
    n_collected: int,
) -> dict[str, dict[str, Any]]:
    """{dimension: {code: figures}} over all agreements with a heat clause."""
    out: dict[str, dict[str, Any]] = {}
    for dimension in (*DIMENSION_NAMES, "families"):
        per_mode = {m: _counts(profiles[m], dimension) for m in MODES}
        passages = {
            m: Counter(
                v for _, c in coded[m] if c["about_heat"] for v in _listed(c, dimension)
            )
            for m in MODES
        }
        out[dimension] = {}
        for code in _values(dimension):
            strict, loose = per_mode["strict"][0][code], per_mode["loose"][0][code]
            if not (strict or loose):
                continue
            verified = (
                sum(
                    code in p["verified"]
                    for p in profiles["loose"].values()
                    if code in p[dimension]
                )
                if dimension == "measures"
                else None
            )
            out[dimension][code] = {
                "label": LABELS[dimension].get(code, code),
                **_cell(strict, loose, n_heat, n_collected),
                "passages_strict": passages["strict"][code],
                "passages_loose": passages["loose"][code],
                "verified_share": _share(verified, loose)
                if verified is not None
                else None,
                "collapsed_strict": len(per_mode["strict"][1][code]),
                "collapsed_loose": len(per_mode["loose"][1][code]),
            }
    return out


def family_blocks(
    profiles: dict[str, dict[str, dict[str, Any]]], n_heat: int, n_collected: int
) -> dict[str, Any]:
    """Per family: its size, and how every dimension splits among its agreements."""
    out: dict[str, Any] = {}
    for family in FAMILY_NAMES:
        members = {
            m: {a: p for a, p in profiles[m].items() if family in p["families"]}
            for m in MODES
        }
        if not members["loose"]:
            continue
        sizes = {m: len(members[m]) for m in MODES}
        block: dict[str, Any] = {
            "label": LABELS["families"][family],
            **_cell(sizes["strict"], sizes["loose"], n_heat, n_collected),
            "collapsed_loose": len({_unit(p) for p in members["loose"].values()}),
            "dimensions": {},
        }
        for dimension in DIMENSION_NAMES:
            per_mode = {m: _counts(members[m], dimension)[0] for m in MODES}
            block["dimensions"][dimension] = {
                code: {
                    "label": LABELS[dimension].get(code, code),
                    "strict": per_mode["strict"][code],
                    "loose": per_mode["loose"][code],
                    "share_strict": _share(per_mode["strict"][code], sizes["strict"]),
                    "share_loose": _share(per_mode["loose"][code], sizes["loose"]),
                }
                for code in _values(dimension)
                if per_mode["strict"][code] or per_mode["loose"][code]
            }
        out[family] = block
    return out


def breakdown(
    profiles: dict[str, dict[str, dict[str, Any]]],
    groups: dict[str, list[str]],
    items: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """{group: {"collected": n, items: {dimension: {code: {strict, loose, share}}}}}.
    `groups` maps a group name to the ids of the agreements collected in it; the share
    is over them. Below `MIN_CELL` agreements the shares are None."""
    out: dict[str, Any] = {}
    for name, ids in groups.items():
        wanted = set(ids)
        counts = {
            m: {
                d: _counts({a: p for a, p in profiles[m].items() if a in wanted}, d)[0]
                for d in items
            }
            for m in MODES
        }
        out[name] = {
            "collected": len(wanted),
            "with_heat_loose": sum(a in wanted for a in profiles["loose"]),
            "items": {
                d: {
                    code: {
                        "strict": counts["strict"][d][code],
                        "loose": counts["loose"][d][code],
                        "share_strict": _share(
                            counts["strict"][d][code], len(wanted), MIN_CELL
                        ),
                        "share_loose": _share(
                            counts["loose"][d][code], len(wanted), MIN_CELL
                        ),
                    }
                    for code in codes
                }
                for d, codes in items.items()
            },
        }
    return out


def cooccurrence(
    profiles: dict[str, dict[str, dict[str, Any]]],
    first: str,
    second: str,
    n_heat: int,
) -> list[dict[str, Any]]:
    """Pairs of values (one from each dimension, or two of the same) that share
    agreements, most frequent first. Jaccard: overlap over the union of the two
    groups; lift: how many times more often than if they were independent."""
    same = first == second
    per_mode: dict[str, Counter[tuple[str, str]]] = {}
    single: dict[str, Counter[str]] = {}
    for mode in MODES:
        pairs: Counter[tuple[str, str]] = Counter()
        singles: Counter[str] = Counter()
        for profile in profiles[mode].values():
            a_values, b_values = profile[first], profile[second]
            singles.update(a_values)
            if not same:
                singles.update(f"{second}:{v}" for v in b_values)
            for a in a_values:
                for b in b_values:
                    if not same or a < b:
                        pairs[(a, b)] += 1
        per_mode[mode], single[mode] = pairs, singles
    loose, strict = per_mode["loose"], per_mode["strict"]
    rows = []
    for (a, b), n_ab in loose.most_common():
        if n_ab < MIN_PAIR:
            break
        n_a = single["loose"][a]
        n_b = single["loose"][b if same else f"{second}:{b}"]
        rows.append(
            {
                "a": a,
                "b": b,
                "a_label": LABELS[first].get(a, a),
                "b_label": LABELS[second].get(b, b),
                "strict": strict[(a, b)],
                "loose": n_ab,
                "jaccard": round(n_ab / (n_a + n_b - n_ab), 3),
                "lift": round(n_ab * n_heat / (n_a * n_b), 2),
            }
        )
    return rows


def family_overlap(
    profiles: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, dict[str, int]]]:
    """{mode: {family: {family: agreements with both}}} (diagonal: the family alone)."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for mode in MODES:
        matrix: dict[str, dict[str, int]] = {
            f: dict.fromkeys(FAMILY_NAMES, 0) for f in FAMILY_NAMES
        }
        for profile in profiles[mode].values():
            for a in profile["families"]:
                for b in profile["families"]:
                    matrix[a][b] += 1
        out[mode] = matrix
    return out


_NUMBER = re.compile(
    r"^\s*(-?\d+(?:[.,]\d+)?)\s*(?:°\s*c?|°c|degr[ée]s?|min(?:utes?)?|mn)?\s*$", re.I
)


def _single_number(value: str) -> float | None:
    """The number when the whole value is one number (with an optional unit), else None:
    ranges, dates and sentences are not guessed at."""
    found = _NUMBER.match(value)
    return float(found.group(1).replace(",", ".")) if found else None


def quantities(profiles: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    """The figures the models read in the clauses, over the loose reading. Per kind:
    agreements giving one, and the most frequent values; for temperatures and
    durations the distribution of the values that are a single number."""
    by_kind: dict[str, dict[str, set[str]]] = {
        k: defaultdict(set) for k in NUMBER_KINDS
    }
    for agreement, profile in profiles["loose"].items():
        for n in profile["numbers"]:
            kind = n["kind"] if n["kind"] in by_kind else "other"
            value = " ".join(str(n["value"]).split())
            if value:
                by_kind[kind][value].add(agreement)
    out: dict[str, Any] = {}
    for kind, values in by_kind.items():
        agreements = set().union(*values.values()) if values else set()
        entry: dict[str, Any] = {
            "agreements": len(agreements),
            "distinct_values": len(values),
            "top_values": [
                [v, len(a)]
                for v, a in sorted(values.items(), key=lambda x: -len(x[1]))[:10]
            ],
        }
        parsed = {v: _single_number(v) for v in values}
        numeric = {v: x for v, x in parsed.items() if x is not None}
        if kind in ("temperature_c", "duration_minutes"):
            entry["single_number_values"] = sum(len(values[v]) for v in numeric)
            entry["not_a_single_number"] = sum(
                len(values[v]) for v in values if v not in numeric
            )
        if kind == "temperature_c":
            thresholds = Counter()
            for v, x in numeric.items():
                if 15 <= x <= 60:
                    thresholds[int(x)] += len(values[v])
            entry["thresholds"] = dict(sorted(thresholds.items()))
        if kind == "duration_minutes":
            buckets = {
                "<=10": 0,
                "11-15": 0,
                "16-20": 0,
                "21-30": 0,
                "31-60": 0,
                ">60": 0,
            }
            for v, x in numeric.items():
                label = (
                    "<=10"
                    if x <= 10
                    else "11-15"
                    if x <= 15
                    else "16-20"
                    if x <= 20
                    else "21-30"
                    if x <= 30
                    else "31-60"
                    if x <= 60
                    else ">60"
                )
                buckets[label] += len(values[v])
            entry["buckets_minutes"] = buckets
        out[kind] = entry
    return out


def cluster_table(
    coded: Sequence[tuple[dict[str, Any], dict[str, Any]]],
    clusters: dict[str, int],
) -> dict[str, Any]:
    """The old k-means clusters against the code-based families and measures, over
    the passages about heat (loose reading):
    {cluster: {passages, heat, families, measures}}."""
    out: dict[int, dict[str, Any]] = {}
    for row, c in coded:
        cluster = clusters.get(row["id"], -1)
        entry = out.setdefault(
            cluster,
            {"passages": 0, "heat": 0, "families": Counter(), "measures": Counter()},
        )
        entry["passages"] += 1
        if c["about_heat"]:
            entry["heat"] += 1
            entry["families"].update(c["families"])
            entry["measures"].update(c["measures"])
    return {
        str(k): {**v, "families": dict(v["families"]), "measures": dict(v["measures"])}
        for k, v in sorted(out.items())
    }


def dataset_block(
    agreements: Sequence[Agreement],
    rows: Sequence[dict[str, Any]],
    profiles: dict[str, dict[str, dict[str, Any]]],
    template_of: dict[str, int],
    relevance: dict[str, int],
) -> dict[str, Any]:
    by_id = {a.id: a for a in agreements}
    kept = {r["agreement_id"] for r in rows}
    groups: dict[int, set[str]] = defaultdict(set)
    passage_agreement = {r["id"]: r["agreement_id"] for r in rows}
    for passage, group in template_of.items():
        groups[group].add(passage_agreement[passage])
    in_template = set().union(*groups.values()) if groups else set()
    heat = profiles["loose"]
    return {
        "collected": len(agreements),
        "years": sorted({(a.signed or "?")[:4] for a in agreements}),
        "kept_passages_agreements": len(kept),
        "passages_coded": len(rows),
        "passages_about_heat_strict": sum(
            consensus(r, "strict")["about_heat"] for r in rows
        ),
        "passages_about_heat_loose": sum(
            consensus(r, "loose")["about_heat"] for r in rows
        ),
        "passages_without_measure_loose": sum(
            not consensus(r, "loose")["measures"] for r in rows
        ),
        "with_heat_clause_strict": len(profiles["strict"]),
        "with_heat_clause_loose": len(heat),
        "without_heat_clause": len(agreements) - len(heat),
        "relevance_labels": relevance,
        "truncated_texts_with_heat": sum(
            len(by_id[a].text) >= TRUNCATED_CHARS for a in heat
        ),
        "other_sources_with_heat": dict(
            Counter(
                by_id[a].content_source
                for a in heat
                if by_id[a].content_source != "api"
            )
        ),
        "template_groups": len(groups),
        "template_largest_group_agreements": max(
            (len(v) for v in groups.values()), default=0
        ),
        "agreements_in_a_template": len(in_template & set(heat)),
        "template_share_of_heat": _share(len(in_template & set(heat)), len(heat)),
    }


def consistency_problems(m: dict[str, Any]) -> list[str]:
    """Things that cannot be true of the figures; an empty list when none is found."""
    problems = []
    d = m["dataset"]
    if d["with_heat_clause_loose"] > d["kept_passages_agreements"]:
        problems.append("more agreements with a heat clause than with a kept passage")
    if d["with_heat_clause_strict"] > d["with_heat_clause_loose"]:
        problems.append("strict heat agreements exceed loose")
    n_heat = d["with_heat_clause_loose"]
    for dimension, codes in m["dimensions"].items():
        for code, c in codes.items():
            residual = dimension == "families" and code == NO_FAMILY
            if c["strict"] > c["loose"] and not residual:
                problems.append(
                    f"{dimension}/{code}: strict {c['strict']} > loose {c['loose']}"
                )
            if c["loose"] > n_heat:
                problems.append(f"{dimension}/{code}: more agreements than {n_heat}")
    for dimension in ("initiative", "pay", "strength"):
        total = sum(c["passages_loose"] for c in m["dimensions"][dimension].values())
        if total != d["passages_about_heat_loose"]:
            problems.append(
                f"{dimension}: {total} passages over its values, "
                f"{d['passages_about_heat_loose']} about heat"
            )
    for family, block in m["families"].items():
        # the residual family is "no agreed measure", larger when strict: not checked
        if family != NO_FAMILY and block["strict"] > block["loose"]:
            problems.append(f"family {family}: strict above loose")
        if block["loose"] > n_heat:
            problems.append(f"family {family}: more agreements than {n_heat}")
    if sum(c["passages"] for c in m["clusters"].values()) != d["passages_coded"]:
        problems.append("cluster table does not cover every coded passage")
    return problems


def build(
    *,
    snapshot_id: str,
    agreements: Sequence[Agreement],
    rows: Sequence[dict[str, Any]],
    profiles: dict[str, dict[str, dict[str, Any]]],
    template_of: dict[str, int],
    clusters: dict[str, int],
    relevance: dict[str, int],
) -> dict[str, Any]:
    coded = {m: [(r, consensus(r, m)) for r in rows] for m in MODES}
    n_heat = len(profiles["loose"])
    n_collected = len(agreements)
    codes = {d: list(_values(d)) for d in ("families", "measures")}

    def by(key) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = defaultdict(list)
        for a in agreements:
            value = key(a)
            if value:
                groups[value].append(a.id)
        return groups

    years = by(lambda a: (a.signed or "")[:4])
    sectors = by(lambda a: a.sector)
    idccs = by(lambda a: a.idcc)

    def top(groups: dict[str, list[str]]) -> dict[str, list[str]]:
        return dict(sorted(groups.items(), key=lambda g: -len(g[1]))[:TOP_GROUPS])

    result: dict[str, Any] = {
        "snapshot": snapshot_id,
        "n_heat": n_heat,
        "n_collected": n_collected,
        "dataset": dataset_block(agreements, rows, profiles, template_of, relevance),
        "dimensions": dimension_table(profiles, coded, n_heat, n_collected),
        "families": family_blocks(profiles, n_heat, n_collected),
        "by_year": breakdown(profiles, dict(sorted(years.items())), codes),
        "by_sector": breakdown(profiles, top(sectors), codes),
        "by_idcc": breakdown(profiles, top(idccs), codes),
        "cooccurrence": {
            "measures_measures": cooccurrence(profiles, "measures", "measures", n_heat),
            "triggers_measures": cooccurrence(profiles, "triggers", "measures", n_heat),
            "triggers_pay": cooccurrence(profiles, "triggers", "pay", n_heat),
            "measures_pay": cooccurrence(profiles, "measures", "pay", n_heat),
            "families": family_overlap(profiles),
        },
        "quantities": quantities(profiles),
        "clusters": cluster_table(coded["loose"], clusters),
    }
    result["problems"] = consistency_problems(result)
    return result
