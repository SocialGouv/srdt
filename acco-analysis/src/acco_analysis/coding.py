"""Coding of the kept passages: what each clause provides, family by family.

Open coding comes first: the model describes freely what a clause does, on a sample of
passages drawn evenly from each family. The descriptions are read by a person and merged
into a codebook, which the closed coding then applies to every passage.
"""

import random
from collections import Counter, defaultdict
from collections.abc import Hashable, Sequence
from typing import Any

from acco_analysis.albert import Albert, AlbertError, run_concurrently
from acco_analysis.codebook import (
    DIMENSIONS,
    NUMBER_KINDS,
    check_values,
    families_of,
    render_codebook,
)
from acco_analysis.label import _fold, verbatim
from acco_analysis.relevance import excerpt

BATCH = 3
WORKERS = 4
EXCERPT_CHARS = 2000
PER_FAMILY = 30

OPEN_SYSTEM = """Tu es juriste en droit du travail français. Tu reçois des extraits \
d'accords d'entreprise qui contiennent un terme lié à la chaleur (canicule, fortes \
chaleurs...). Pour chaque extrait, décris librement, sans grille préétablie, ce que la \
clause prévoit à propos de la chaleur. Reste fidèle au texte : n'ajoute rien qu'il ne dit pas.

Réponds uniquement avec un objet JSON :
{"results": [{
 "id": "<id>",
 "about_heat": "<true si l'extrait prévoit quelque chose à propos de la chaleur, false sinon>",
 "trigger": "<ce qui déclenche la mesure : vigilance, seuil de température, décision de \
l'employeur... ou null>",
 "measures": ["<chaque mesure prévue, en quelques mots>"],
 "scope": "<qui est concerné, ou null>",
 "conditions": "<procédure, accord du salarié, délai de prévenance, limites... ou null>",
 "pay": "<effet sur la rémunération, ou null>",
 "numbers": ["<chaque chiffre du texte avec son unité et ce qu'il désigne>"],
 "other": "<tout ce qui est notable et ne rentre dans aucun champ ci-dessus, ou null>",
 "quote": "<une citation de 250 caractères maximum, copiée mot pour mot, qui montre la mesure>"
}]}"""


def family_of_clusters(families: dict[str, Any]) -> dict[int, int]:
    """{cluster id: index of its family in families.json}."""
    return {
        cluster: n
        for n, family in enumerate(families["families"])
        for cluster in family["clusters"]
    }


def sample_by_family(
    passages: Sequence[dict[str, Any]],
    assignments: dict[str, int],
    families: dict[str, Any],
    per_family: int = PER_FAMILY,
    seed: int = 0,
) -> dict[int, list[dict[str, Any]]]:
    """`per_family` passages of each family, spread evenly over its clusters and then
    drawn at random inside each cluster, so the sample covers the range of a family and
    not only its largest cluster."""
    family_of = family_of_clusters(families)
    rng = random.Random(seed)
    pools: dict[int, dict[int, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for p in passages:
        cluster = assignments.get(p["id"], -1)
        if cluster in family_of:
            pools[family_of[cluster]][cluster].append(p)
    sample: dict[int, list[dict[str, Any]]] = {}
    for family, by_cluster in sorted(pools.items()):
        for members in by_cluster.values():
            rng.shuffle(members)
        chosen: list[dict[str, Any]] = []
        queues = [by_cluster[c] for c in sorted(by_cluster)]
        while len(chosen) < per_family and any(queues):
            for queue in queues:
                if queue and len(chosen) < per_family:
                    chosen.append(queue.pop())
        sample[family] = chosen
    return sample


def _prompt(batch: Sequence[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"### [{p['id']}]\nTitre : {p['heading'] or '(sans titre)'}\n"
        f"{excerpt(p['text'], EXCERPT_CHARS)}"
        for p in batch
    )


def _parse_open(
    answer: Any, by_id: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    results = answer.get("results") if isinstance(answer, dict) else None
    parsed: dict[str, dict[str, Any]] = {}
    for item in results or []:
        if not isinstance(item, dict) or item.get("id") not in by_id:
            continue
        passage = by_id[item["id"]]
        quote = str(item.get("quote") or "")
        item = dict(item)
        item["quote"] = quote.strip() if verbatim(quote, passage["text"]) else None
        parsed[item["id"]] = item
    return parsed


def open_coding_markdown(rows: Sequence[dict[str, Any]]) -> str:
    """The descriptions, family by family, for a person to read."""
    out = ["# Open coding", ""]
    family = None
    for r in rows:
        if r["family"] != family:
            family = r["family"]
            out += [f"## {family + 1}. {r['family_label']}", ""]
        heat = "" if r.get("about_heat") is not False else " [NOT ABOUT HEAT]"
        out += [f"### {r['id']} (cluster {r['cluster'] + 1}){heat}", ""]
        for key in ("trigger", "scope", "conditions", "pay", "other"):
            if r.get(key):
                out.append(f"- {key}: {r[key]}")
        if r.get("measures"):
            out.append("- measures: " + "; ".join(map(str, r["measures"])))
        if r.get("numbers"):
            out.append("- numbers: " + "; ".join(map(str, r["numbers"])))
        out += [
            "",
            f"> {r['quote']}" if r.get("quote") else "> (no verified quote)",
            "",
        ]
    return "\n".join(out) + "\n"


def open_code(
    albert: Albert, passages: Sequence[dict[str, Any]], batch: int = BATCH
) -> dict[str, dict[str, Any]]:
    """{passage id: free description}. A passage the model skipped is asked again alone;
    a quote that is not in the passage is replaced by None."""
    groups = [passages[i : i + batch] for i in range(0, len(passages), batch)]

    def run(group: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        by_id = {p["id"]: p for p in group}
        return _parse_open(albert.chat_json(OPEN_SYSTEM, _prompt(group)), by_id)

    coded: dict[str, dict[str, Any]] = {}
    for part in run_concurrently(run, groups, WORKERS):
        coded.update(part)
    for p in passages:
        if p["id"] not in coded:
            coded.update(run([p]))
    missing = [p["id"] for p in passages if p["id"] not in coded]
    if missing:
        raise RuntimeError(f"{len(missing)} passages not coded, e.g. {missing[0]}")
    return coded


CLOSED_BATCH = 3
QUOTE_CHARS = 120
MIN_QUOTE = 8

CLOSED_SYSTEM = f"""Tu es juriste en droit du travail français. Tu reçois des extraits \
d'accords d'entreprise qui contiennent un terme lié à la chaleur (canicule, fortes \
chaleurs...). Pour chaque extrait, renseigne la grille ci-dessous à partir de ce que le \
texte dit, et de rien d'autre : ce qui n'est pas écrit est "unspecified" ou "none", jamais \
déduit. Une mesure n'est retenue que si l'extrait la prévoit à propos de la chaleur.

Grille :
{render_codebook()}

Pour chaque mesure, "quote" est une citation de {QUOTE_CHARS} caractères maximum, copiée \
mot pour mot d'un seul tenant dans l'extrait (sans « ... », sans reformuler) qui la montre. \
Si tu utilises la mesure "other", décris-la dans "other_measure". "about_heat" vaut false \
si l'extrait ne prévoit rien à propos de la chaleur (simple mention).

Réponds uniquement avec un objet JSON :
{{"results": [{{"id": "<id>", "about_heat": true, \
"measures": [{{"code": "<code>", "quote": "<citation>"}}], "other_measure": null, \
"triggers": ["<code>"], "initiative": "<code>", "scope": ["<code>"], "pay": "<code>", \
"procedure": ["<code>"], "strength": "<code>", \
"numbers": [{{"kind": "{"|".join(NUMBER_KINDS)}", "value": "<valeur>", \
"what": "<ce que désigne le chiffre>"}}], "note": null}}]}}"""


def quote_in_text(quote: str, text: str) -> bool:
    """Is `quote` in `text`, up to case, spacing and accent encoding? Short quotes are
    accepted (a measure is often named in a few words)."""
    q = _fold(quote).strip(" .…\"'«»")
    return len(q) >= MIN_QUOTE and q in _fold(text)


def clean_closed(item: dict[str, Any], text: str) -> dict[str, Any]:
    """One model answer, checked against the codebook and the passage.

    A value outside the codebook is dropped and listed in `unknown`. A measure whose
    quote is not in the passage is kept (the quote may be badly copied while the measure
    is right) and marked `verified: false`."""
    unknown: dict[str, list[str]] = {}
    clean: dict[str, Any] = {}
    for d in DIMENSIONS:
        values, bad = check_values(d, item.get(d.name))
        clean[d.name] = values if d.multi else (values[0] if values else None)
        if bad:
            unknown[d.name] = bad
    quotes: dict[str, str] = {}
    for raw in item.get("measures") or []:
        if isinstance(raw, dict) and isinstance(raw.get("code"), str):
            quotes.setdefault(raw["code"], str(raw.get("quote") or ""))
    clean["measures"] = [
        {
            "code": code,
            "quote": quotes[code].strip() if quotes.get(code) else None,
            "verified": quote_in_text(quotes.get(code, ""), text),
        }
        for code in clean["measures"]
    ]
    clean["numbers"] = [
        {
            "kind": n["kind"] if n.get("kind") in NUMBER_KINDS else "other",
            "value": str(n.get("value", "")),
            "what": str(n.get("what", "")),
        }
        for n in item.get("numbers") or []
        if isinstance(n, dict)
    ]
    heat = item.get("about_heat")
    clean["about_heat"] = heat not in (False, "false", "False")
    clean["other_measure"] = item.get("other_measure") or None
    clean["note"] = item.get("note") or None
    clean["unknown"] = unknown
    clean["families"] = families_of({m["code"] for m in clean["measures"]})
    return clean


def _owner(item: dict[str, Any], by_id: dict[str, Any]) -> str | None:
    """The passage an answer belongs to. A model sometimes answers per numbered section
    of a passage, with ids like `<passage id>_6-7`."""
    given = item.get("id")
    if given in by_id:
        return given
    for i in by_id:
        if isinstance(given, str) and given.startswith(f"{i}_"):
            return i
    return None


def _merge_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    """One answer for a passage the model split into several: the answers about heat
    are merged (multi-valued dimensions unite, a single value is the first one)."""
    if len(items) == 1:
        return items[0]
    heat = [x for x in items if x.get("about_heat") not in (False, "false", "False")]
    if not heat:
        return items[0]
    merged = dict(heat[0])
    for d in DIMENSIONS:
        if d.multi:
            union: list[Any] = []
            for x in heat:
                for v in x.get(d.name) or []:
                    code = v.get("code") if isinstance(v, dict) else v
                    if all(
                        (u.get("code") if isinstance(u, dict) else u) != code
                        for u in union
                    ):
                        union.append(v)
            merged[d.name] = union
    merged["numbers"] = [n for x in heat for n in x.get("numbers") or []]
    return merged


def code_passages(
    albert: Albert, passages: Sequence[dict[str, Any]], batch: int = CLOSED_BATCH
) -> dict[str, dict[str, Any]]:
    """{passage id: coded passage}. A passage the model skipped, or whose answer was not
    valid JSON, is asked again alone; one that still fails is absent from the result."""
    groups = [passages[i : i + batch] for i in range(0, len(passages), batch)]

    def run(group: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        by_id = {p["id"]: p for p in group}
        try:
            answer = albert.chat_json(CLOSED_SYSTEM, _prompt(group), max_tokens=8000)
        except AlbertError:  # e.g. an answer cut off in the middle of the JSON
            return {}
        results = answer.get("results") if isinstance(answer, dict) else None
        found: dict[str, list[dict[str, Any]]] = {}
        for item in results or []:
            owner = _owner(item, by_id) if isinstance(item, dict) else None
            if owner:
                found.setdefault(owner, []).append(item)
        return {
            i: clean_closed(_merge_items(items), by_id[i]["text"])
            for i, items in found.items()
        }

    coded: dict[str, dict[str, Any]] = {}
    for part in run_concurrently(run, groups, WORKERS):
        coded.update(part)
    for p in passages:
        if p["id"] not in coded:
            coded.update(run([p]))
    return coded


def kappa(xs: Sequence[Hashable], ys: Sequence[Hashable]) -> float | None:
    """Cohen's kappa of two raters over the same items; None when chance agreement is
    total (one value only), where the figure means nothing."""
    n = len(xs)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(xs, ys, strict=True)) / n
    cx, cy = Counter(xs), Counter(ys)
    chance = sum(cx[v] * cy[v] for v in cx.keys() | cy.keys()) / n**2
    return None if chance == 1 else round((observed - chance) / (1 - chance), 3)


def _jaccard(a: set[str], b: set[str]) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def _codes(coded: dict[str, Any], dimension: str) -> set[str]:
    return {x["code"] if isinstance(x, dict) else x for x in coded[dimension]}


def reliability(
    main: dict[str, dict[str, Any]],
    check: dict[str, dict[str, Any]],
    min_count: int = 5,
) -> dict[str, Any]:
    """Agreement of two models on the same passages, per dimension, and per code for the
    codes that at least one model gave `min_count` times."""
    ids = sorted(main.keys() & check.keys())
    report: dict[str, Any] = {"passages": len(ids)}
    if not ids:
        return report
    for d in DIMENSIONS:
        if d.multi:
            sets = [(_codes(main[i], d.name), _codes(check[i], d.name)) for i in ids]
            entry: dict[str, Any] = {
                "mean_jaccard": round(
                    sum(_jaccard(a, b) for a, b in sets) / len(ids), 3
                ),
                "exact_match": round(sum(a == b for a, b in sets) / len(ids), 3),
            }
            codes: dict[str, Any] = {}
            for code in d.values:
                a = [code in x for x, _ in sets]
                b = [code in y for _, y in sets]
                if max(sum(a), sum(b)) >= min_count:
                    codes[code] = {
                        "main": sum(a),
                        "check": sum(b),
                        "kappa": kappa(a, b),
                    }
            entry["codes"] = codes
        else:
            a = [main[i][d.name] for i in ids]
            b = [check[i][d.name] for i in ids]
            entry = {
                "agreement": round(
                    sum(x == y for x, y in zip(a, b, strict=True)) / len(ids), 3
                ),
                "kappa": kappa(a, b),
            }
        report[d.name] = entry
    return report


def summarise(coded: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Counts that tell whether the codebook fits: how often the model had to say
    "other", used a value outside the codebook, or gave a quote that is not in the
    passage."""
    rows = list(coded.values())
    measures = [m for r in rows for m in r["measures"]]
    unknown: Counter[str] = Counter()
    for r in rows:
        for dimension, values in r["unknown"].items():
            unknown[dimension] += len(values)
    return {
        "passages": len(rows),
        "not_about_heat": sum(not r["about_heat"] for r in rows),
        "no_measure": sum(not r["measures"] for r in rows),
        "measure_other_rate": round(
            sum(m["code"] == "other" for m in measures) / max(len(measures), 1), 3
        ),
        "passages_with_other_measure": sum(
            any(m["code"] == "other" for m in r["measures"]) for r in rows
        ),
        "unverified_quote_rate": round(
            sum(not m["verified"] for m in measures) / max(len(measures), 1), 3
        ),
        "values_outside_codebook": dict(unknown),
        "measures": dict(Counter(m["code"] for m in measures).most_common()),
        "families": dict(Counter(f for r in rows for f in r["families"]).most_common()),
        "scope_unspecified": sum(r["scope"] == ["unspecified"] for r in rows),
        "pay": dict(Counter(r["pay"] for r in rows)),
        "strength": dict(Counter(r["strength"] for r in rows)),
    }
