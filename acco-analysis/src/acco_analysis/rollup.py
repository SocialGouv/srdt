"""Roll-up of the closed coding: what the two models say together, one profile per
agreement, and the clauses shared between agreements (templates).

Two readings of every code, since the models disagree on some and nothing has been
validated by hand yet: `strict` keeps what both models gave, `loose` what either gave.
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import numpy as np

from acco_analysis.codebook import DIMENSIONS, families_of
from acco_analysis.label import _fold

MODES = ("strict", "loose")
MULTI = tuple(d.name for d in DIMENSIONS if d.multi)
SINGLE = tuple(d.name for d in DIMENSIONS if not d.multi)
DISAGREE = "models_disagree"
UNKNOWN = "unknown"  # the model gave no value for a single-valued dimension
# the API cut long texts at about this many characters
TRUNCATED_CHARS = 98_000
NEAR_DUPLICATE = 0.95


def _codes(coded: dict[str, Any], dimension: str) -> set[str]:
    return {x["code"] if isinstance(x, dict) else x for x in coded[dimension]}


def _verified(coded: dict[str, Any]) -> set[str]:
    return {m["code"] for m in coded["measures"] if m.get("verified")}


def consensus(row: dict[str, Any], mode: str) -> dict[str, Any]:
    """One coding of a passage from the two models: codes both gave (strict) or either
    gave (loose); a single-valued dimension takes the value both gave, else
    `DISAGREE`."""
    main, check = row["main"], row["check"]
    strict = mode == "strict"
    out: dict[str, Any] = {
        "about_heat": (main["about_heat"] and check["about_heat"])
        if strict
        else (main["about_heat"] or check["about_heat"]),
    }
    for name in MULTI:
        a, b = _codes(main, name), _codes(check, name)
        out[name] = a & b if strict else a | b
    for name in SINGLE:
        a, b = main[name] or UNKNOWN, check[name] or UNKNOWN
        out[name] = a if a == b else DISAGREE
    out["verified"] = _verified(main) | _verified(check)
    seen: set[tuple[str, str]] = set()
    numbers = []
    for n in main["numbers"] + check["numbers"]:
        key = (n["kind"], n["value"])
        if key not in seen:
            seen.add(key)
            numbers.append(n)
    out["numbers"] = numbers
    out["families"] = families_of(out["measures"])
    return out


def agreement_profiles(
    rows: Sequence[dict[str, Any]],
    mode: str,
    template_of: dict[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """{agreement id: profile}, for the agreements with a passage about heat.

    A profile is the union over the agreement's heat passages: every dimension is a
    set of values (an agreement can have several initiatives, for example)."""
    template_of = template_of or {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["agreement_id"]].append(row)
    profiles: dict[str, dict[str, Any]] = {}
    for agreement, members in grouped.items():
        coded = [(m, consensus(m, mode)) for m in members]
        heat = [(m, c) for m, c in coded if c["about_heat"]]
        if not heat:
            continue
        profile: dict[str, Any] = {
            "agreement_id": agreement,
            "mode": mode,
            "passages": len(heat),
            "passages_total": len(members),
            "passage_ids": [m["id"] for m, _ in heat],
            "families": sorted({f for _, c in heat for f in c["families"]}),
            "verified": sorted(set().union(*(c["verified"] for _, c in heat))),
            "numbers": [n for _, c in heat for n in c["numbers"]],
        }
        for name in (*MULTI, *SINGLE):
            values = set().union(
                *(c[name] if name in MULTI else {c[name]} for _, c in heat)
            )
            profile[name] = sorted(values)
        sizes = defaultdict(int)
        for m, _ in heat:
            if m["id"] in template_of:
                sizes[template_of[m["id"]]] += 1
        profile["template"] = (
            max(sizes, key=lambda g: (sizes[g], -g)) if sizes else None
        )
        profiles[agreement] = profile
    return profiles


def template_groups(
    ids: Sequence[str],
    agreement_ids: Sequence[str],
    texts: Sequence[str],
    vectors: np.ndarray,
    threshold: float = NEAR_DUPLICATE,
) -> dict[str, int]:
    """{passage id: template group} for the passages that say (nearly) the same as a
    passage of another agreement: same text once normalised, or cosine similarity of
    the embeddings at least `threshold`. A passage repeated inside one agreement is not
    a template. Group numbers follow the first member's position."""
    n = len(ids)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        a, b = find(i), find(j)
        if a != b:
            parent[max(a, b)] = min(a, b)

    by_text: dict[str, list[int]] = defaultdict(list)
    for i, text in enumerate(texts):
        by_text[" ".join(_fold(text).split())].append(i)
    for members in by_text.values():
        for i in members[1:]:
            if agreement_ids[i] != agreement_ids[members[0]]:
                union(members[0], i)

    unit = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)
    for start in range(0, n, 1000):
        sims = unit[start : start + 1000] @ unit.T
        rows, cols = np.nonzero(sims >= threshold)
        for r, c in zip(rows.tolist(), cols.tolist(), strict=True):
            i = start + r
            if c > i and agreement_ids[c] != agreement_ids[i]:
                union(i, c)

    members_of: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        members_of[find(i)].append(i)
    groups = [m for m in members_of.values() if len({agreement_ids[i] for i in m}) > 1]
    groups.sort(key=lambda m: m[0])
    return {ids[i]: g for g, m in enumerate(groups) for i in m}
