"""Flavours of the heat clauses inside each family: recurring combinations of codes.

The combinations and their counts come from counting the agreement profiles (strict
reading: what both models coded), never from the model. The model only writes the name
and the description of a flavour from its members, with quotes checked against the
passage text.

A flavour is a set of codes (for example schedule shift + vigilance orange + pay
maintained). They are found greedily: the most specific frequent combination first, its
agreements are set aside, and the search goes on with the rest, so the flavours of a
family do not overlap and are ranked by the order they were found in.
"""

import random
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any

import numpy as np

from acco_analysis.albert import Albert, run_concurrently
from acco_analysis.cluster import nearest
from acco_analysis.codebook import FAMILIES
from acco_analysis.corpus import Agreement
from acco_analysis.extract import PHRASE_RE, VARIANT_RE
from acco_analysis.label import QUOTE_CHARS, verbatim
from acco_analysis.metrics import LABELS, _share, _unit, wilson
from acco_analysis.relevance import excerpt
from acco_analysis.rollup import DISAGREE, UNKNOWN, consensus

DISCOVERY = ("measures", "triggers", "pay")
# in the telework family the measure never varies: what tells clauses apart is who
# asks, who agrees and for whom
DISCOVERY_BY_FAMILY = {
    "telework": ("measures", "triggers", "initiative", "procedure", "scope"),
}
COLOURS = {"vigilance_yellow", "vigilance_orange", "vigilance_red"}
COLOURED = "vigilance_coloured"
# a trigger that names a condition; "canicule" alone is only what the models write when
# the text gives no better one (the codebook says so), so it gives way to these
SPECIFIC_TRIGGERS = {
    *COLOURS,
    "vigilance_unspecified",
    "temperature_threshold",
    "fixed_period",
    "workplace_temperature",
    "employer_decision",
}
# values that say nothing about the clause: not used to tell flavours apart
IGNORED = {"unspecified", "none", "other", "reference_only", DISAGREE, UNKNOWN}
DESCRIBED = (
    "measures",
    "triggers",
    "pay",
    "scope",
    "initiative",
    "procedure",
    "strength",
)
MIN_SUPPORT = 10
MIN_SHARE = 0.03
CONSTANT = 0.95  # a code in this share of a family does not tell flavours apart
MAX_SIZE = 3
MAX_FLAVOURS = 10
SHOWN_CENTRAL = 6
SHOWN_OUTLYING = 2
EXCERPT_CHARS = 900
MIN_DISTRIBUTION = 0.10
WORKERS = 4

SYSTEM = """Tu es juriste en droit du travail français. Tu reçois un type de clause « chaleur » \
(canicule, fortes chaleurs...) retrouvé dans plusieurs accords d'entreprise. Il est défini par \
une combinaison de caractéristiques déjà établies et comptées ; on te donne aussi la répartition \
des autres caractéristiques parmi ces accords et quelques extraits représentatifs.

Décris uniquement ce que montrent les extraits et les caractéristiques fournies. Ne recalcule \
aucun chiffre et n'en invente pas.

Réponds uniquement avec un objet JSON :
{
 "name": "<nom du type de clause, 8 mots max, qui reflète ce qui le définit>",
 "description": "<2 à 3 phrases : ce que prévoit la clause, quand elle s'applique, pour qui, sous quelles conditions>",
 "variations": ["<variante observée dans les extraits, 1 phrase>"],
 "quotes": [{"id": "<id de l'extrait>", "quote": "<citation copiée mot pour mot>"}]
}
Donne 0 à 3 variantes et 4 citations de 300 caractères maximum, copiées exactement (sans \
reformuler, sans « … ») depuis des extraits différents."""
MIN_QUOTES = 3
RETRY = (
    "\n\nTes citations précédentes étaient trop peu nombreuses ou pas copiées mot pour mot. "
    "Donne 4 citations exactes (une phrase ou deux), chacune d'un extrait différent."
)


def _features(values: Mapping[str, Any], dims: Sequence[str]) -> frozenset[str]:
    out = set()
    for d in dims:
        raw = values[d]
        codes = {raw} if isinstance(raw, str) else set(raw)
        if d == "triggers":
            if codes & SPECIFIC_TRIGGERS:
                codes.discard("canicule_unqualified")
            if codes & COLOURS:
                codes = (codes - COLOURS) | {COLOURED}
        out |= {f"{d}:{c}" for c in codes if c not in IGNORED}
    return frozenset(out)


def items_of(
    profile: Mapping[str, Any], dims: Sequence[str] = DISCOVERY
) -> frozenset[str]:
    """The discovery features of an agreement profile, as `dimension:code`."""
    return _features(profile, dims)


def passage_items(
    coded: Mapping[str, Any], dims: Sequence[str] = DISCOVERY
) -> frozenset[str]:
    """`items_of` for the coding of one passage (see rollup.consensus)."""
    return _features(coded, dims)


def weight(item: str) -> int:
    """How much an item makes a combination specific: a named trigger or a pay effect
    says more than a measure or a bare "canicule"."""
    dimension, code = item.split(":", 1)
    named = code in SPECIFIC_TRIGGERS or code == COLOURED
    return 2 if named or dimension == "pay" else 1


def find_flavours(
    members: Mapping[str, frozenset[str]],
    min_support: int,
    max_flavours: int = MAX_FLAVOURS,
    max_size: int = MAX_SIZE,
) -> tuple[list[tuple[tuple[str, ...], list[str]]], list[str], list[str]]:
    """(flavours, left over, constant items) of one family.

    `members` maps an agreement to its items. A flavour is (items, agreement ids): the
    combination of at most `max_size` items, each rare or common enough to be told
    apart, that scores highest on support x specificity squared among the agreements not yet
    placed (specific combinations first, but only when enough agreements share them).
    Items present in nearly every agreement are reported as constant and left out."""
    n = len(members)
    counts = Counter(i for items in members.values() for i in items)
    constant = sorted(i for i, c in counts.items() if c >= CONSTANT * n)
    universe = {i for i, c in counts.items() if c >= min_support} - set(constant)
    remaining = {a: items & universe for a, items in members.items()}
    flavours: list[tuple[tuple[str, ...], list[str]]] = []
    while len(flavours) < max_flavours and remaining:
        counts = Counter(i for items in remaining.values() for i in items)
        frequent = sorted(i for i, c in counts.items() if c >= min_support)
        best: tuple[tuple[int, int, tuple[str, ...]], list[str]] | None = None
        for size in range(1, max_size + 1):
            for combo in combinations(frequent, size):
                wanted = set(combo)
                ids = [a for a, items in remaining.items() if wanted <= items]
                if len(ids) < min_support:
                    continue
                specificity = sum(weight(i) for i in combo)
                key = (len(ids) * specificity**2, len(ids), tuple(sorted(combo)))
                if best is None or key > best[0]:
                    best = (key, ids)
        if best is None:
            break
        combo = best[0][2]
        flavours.append((combo, sorted(best[1])))
        for a in best[1]:
            del remaining[a]
    return flavours, sorted(remaining), constant


def _label(item: str) -> str:
    dimension, code = item.split(":", 1)
    if code == COLOURED:
        return "vigilance orange, rouge ou jaune"
    return LABELS[dimension].get(code, code)


def distributions(
    profiles: Sequence[Mapping[str, Any]], minimum: float = MIN_DISTRIBUTION
) -> dict[str, list[dict[str, Any]]]:
    """Per dimension, the values present in at least `minimum` of the profiles."""
    out: dict[str, list[dict[str, Any]]] = {}
    n = len(profiles)
    for d in DESCRIBED:
        counts = Counter(v for p in profiles for v in p[d])
        rows = [
            {
                "code": c,
                "label": LABELS[d].get(c, c),
                "agreements": k,
                "share": round(k / n, 3),
            }
            for c, k in counts.most_common()
            if k / n >= minimum
        ]
        if rows:
            out[d] = rows
    return out


def representatives(
    candidates: Sequence[int],
    vectors: np.ndarray,
    units: Sequence[str],
    seed: int = 0,
) -> list[int]:
    """Passages to show for a flavour: the most central ones, then a few drawn at random
    for the range, one per template or agreement so that a shared clause is shown once.
    `candidates` index `vectors` and `units`."""
    ordered = nearest(vectors, np.array(candidates), len(candidates))
    chosen: list[int] = []
    used: set[str] = set()
    for i in ordered:
        if units[i] not in used and len(chosen) < SHOWN_CENTRAL:
            chosen.append(i)
            used.add(units[i])
    rest = [i for i in ordered if units[i] not in used]
    rng = random.Random(seed)
    for i in rng.sample(rest, min(len(rest), SHOWN_OUTLYING * 3)):
        if units[i] not in used and len(chosen) < SHOWN_CENTRAL + SHOWN_OUTLYING:
            chosen.append(i)
            used.add(units[i])
    return chosen


def _facts(
    flavour: dict[str, Any], family_label: str, siblings: Sequence[str] = ()
) -> str:
    lines = [
        f"Famille : {family_label}",
        f"Accords concernés : {flavour['strict']} (sur {flavour['family_strict']} de la famille)",
        "Caractéristiques qui définissent ce type : "
        + " ; ".join(c["label"] for c in flavour["codes"]),
        "Répartition des autres caractéristiques (part de ces accords) :",
    ]

    for d, rows in flavour["distributions"].items():
        lines.append(
            f"- {d} : " + ", ".join(f"{r['label']} {r['share']:.0%}" for r in rows)
        )
    if siblings:
        lines.append(
            "Autres types de la même famille (le nom doit se démarquer d'eux, en "
            "reflétant ce qui définit celui-ci) :"
        )
        lines += [f"- {sibling}" for sibling in siblings]
    return "\n".join(lines)


def _checked(
    answer: dict[str, Any], by_id: Mapping[str, dict[str, Any]]
) -> tuple[list[dict[str, str]], int]:
    """The quotes of an answer that are in their passage (once per passage), and how
    many were dropped."""
    quotes: list[dict[str, str]] = []
    dropped = 0
    for item in answer.get("quotes") or []:
        passage = by_id.get(str(item.get("id"))) if isinstance(item, dict) else None
        quote = str(item.get("quote", "")) if isinstance(item, dict) else ""
        if (
            passage
            and verbatim(quote, passage["text"])
            and all(q["id"] != passage["id"] for q in quotes)
        ):
            quotes.append({"id": passage["id"], "quote": quote.strip()[:QUOTE_CHARS]})
        else:
            dropped += 1
    return quotes, dropped


def _sentence(text: str) -> str | None:
    """The sentence of a passage that says most about heat, short enough to quote."""
    best, best_score = None, 0
    for part in re.split(r"(?<=[.;!?])\s+|\n+", text):
        part = part.strip(" -•\t")
        if 40 <= len(part) <= QUOTE_CHARS:
            score = len(PHRASE_RE.findall(part)) * 2 + len(VARIANT_RE.findall(part))
            if score > best_score:
                best, best_score = part, score
    return best


def _fill(
    quotes: list[dict[str, str]], shown: Sequence[dict[str, Any]]
) -> list[dict[str, str]]:
    """Add a sentence from the shown passages (most central first) until there are
    `MIN_QUOTES` quotes, one per passage."""
    quotes = list(quotes)
    for p in shown:
        if len(quotes) >= MIN_QUOTES:
            break
        sentence = _sentence(p["text"])
        if sentence and all(q["id"] != p["id"] for q in quotes):
            quotes.append({"id": p["id"], "quote": sentence})
    return quotes


def describe(
    albert: Albert,
    flavour: dict[str, Any],
    family_label: str,
    shown: Sequence[dict[str, Any]],
    siblings: Sequence[str] = (),
) -> dict[str, Any]:
    """Name, description and checked quotes of one flavour, from the facts and the shown
    passages. A quote that is not in its passage is dropped and counted."""
    user = (
        _facts(flavour, family_label, siblings)
        + "\n\nExtraits :\n\n"
        + "\n\n".join(
            f"### [{p['id']}]\nTitre : {p['heading'] or '(sans titre)'}\n"
            f"{excerpt(p['text'], EXCERPT_CHARS)}"
            for p in shown
        )
    )
    by_id = {p["id"]: p for p in shown}
    answer = albert.chat_json(SYSTEM, user, max_tokens=2500)
    quotes, dropped = _checked(answer, by_id)
    if len(quotes) < min(MIN_QUOTES, len(shown)):
        # one more try asking for exact quotes; what is still missing is taken from
        # the passages themselves
        retry = albert.chat_json(SYSTEM, user + RETRY, max_tokens=2500)
        again = [
            q
            for q in _checked(retry, by_id)[0]
            if q["id"] not in {x["id"] for x in quotes}
        ]
        quotes = _fill(quotes + again, shown)
    return {
        "name": str(answer.get("name", "")).strip(),
        "description": str(answer.get("description", "")).strip(),
        "variations": [str(v) for v in answer.get("variations") or []],
        "quotes": quotes,
        "quotes_dropped": dropped,
    }


def build(
    *,
    albert: Albert | None,
    agreements: Sequence[Agreement],
    rows: Sequence[dict[str, Any]],
    profiles: dict[str, dict[str, dict[str, Any]]],
    passages: Sequence[dict[str, Any]],
    vectors: np.ndarray,
    template_of: Mapping[str, int],
    min_share: float = MIN_SHARE,
) -> dict[str, Any]:
    """The flavours of every family. With `albert` None the counting is done and the
    descriptions are left empty (the discovery is checked and costs nothing)."""
    by_agreement = {a.id: a for a in agreements}
    position = {p["id"]: i for i, p in enumerate(passages)}
    row_of = {r["id"]: r for r in rows}
    strict, loose = profiles["strict"], profiles["loose"]
    units = [
        f"t{template_of[p['id']]}" if p["id"] in template_of else p["agreement_id"]
        for p in passages
    ]
    families: dict[str, Any] = {}
    jobs: list[tuple[str, int, list[dict[str, Any]]]] = []
    for family in FAMILIES:  # not the residual family: it has no measure to vary
        ids = [a for a, p in strict.items() if family in p["families"]]
        if len(ids) < MIN_SUPPORT:
            continue
        label = LABELS["families"][family]
        dims = DISCOVERY_BY_FAMILY.get(family, DISCOVERY)
        found, left, constant = find_flavours(
            {a: items_of(strict[a], dims) for a in ids},
            max(MIN_SUPPORT, round(min_share * len(ids))),
        )
        loose_ids = [a for a, p in loose.items() if family in p["families"]]
        flavour_rows = []
        for n, (codes, members) in enumerate(found, 1):
            wanted = set(codes)
            member_profiles = [strict[a] for a in members]
            # the family's passages of each member that carry the most of its codes
            candidates = []
            for a in members:
                best, best_score = None, -1
                for pid in strict[a]["passage_ids"]:
                    c = consensus(row_of[pid], "strict")
                    if (
                        family in c["families"]
                        and len(wanted & passage_items(c)) > best_score
                    ):
                        best, best_score = pid, len(wanted & passage_items(c))
                if best:
                    candidates.append(position[best])
            shown_idx = (
                representatives(candidates, vectors, units, seed=n)
                if candidates
                else []
            )
            years = Counter((by_agreement[a].signed or "?")[:4] for a in members)
            sectors = Counter(
                by_agreement[a].sector for a in members if by_agreement[a].sector
            )
            flavour = {
                "id": f"{family}-{n}",
                "rank": n,
                "codes": [{"item": i, "label": _label(i)} for i in codes],
                "strict": len(members),
                "family_strict": len(ids),
                "share_of_family": _share(len(members), len(ids)),
                "ci": wilson(len(members), len(ids)),
                "loose": sum(wanted <= items_of(loose[a], dims) for a in loose_ids),
                "collapsed": len({_unit(strict[a]) for a in members}),
                "agreements": members,
                "distributions": distributions(member_profiles),
                "years": dict(sorted(years.items())),
                "top_sectors": sectors.most_common(3),
                "shown": [passages[i]["id"] for i in shown_idx],
            }
            flavour_rows.append(flavour)
            jobs.append((family, n - 1, [passages[i] for i in shown_idx]))
        families[family] = {
            "label": label,
            "strict": len(ids),
            "loose": len(loose_ids),
            "constant": [{"item": i, "label": _label(i)} for i in constant],
            "min_support": max(MIN_SUPPORT, round(min_share * len(ids))),
            "flavours": flavour_rows,
            "other": {
                "agreements": left,
                "strict": len(left),
                "share_of_family": _share(len(left), len(ids)),
                "distributions": distributions([strict[a] for a in left])
                if left
                else {},
            },
        }

    if albert is not None:

        def run(job: tuple[str, int, list[dict[str, Any]]]) -> dict[str, Any]:
            family, index, shown = job
            flavour = families[family]["flavours"][index]
            siblings = [
                " + ".join(c["label"] for c in other["codes"])
                for other in families[family]["flavours"]
                if other is not flavour
            ]
            return describe(albert, flavour, families[family]["label"], shown, siblings)

        for (family, index, _), result in zip(
            jobs, run_concurrently(run, jobs, WORKERS), strict=True
        ):
            flavour = families[family]["flavours"][index]
            flavour.update(result)
            flavour["quotes"] = [
                {
                    **q,
                    "company": by_agreement[
                        passages[position[q["id"]]]["agreement_id"]
                    ].company,
                    "signed": by_agreement[
                        passages[position[q["id"]]]["agreement_id"]
                    ].signed,
                    "url": by_agreement[
                        passages[position[q["id"]]]["agreement_id"]
                    ].url,
                }
                for q in flavour["quotes"]
            ]
    return {"families": families}
