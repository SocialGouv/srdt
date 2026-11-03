"""Stage 5: out/clauses.json and out/clauses.md, the flavours of the heat clauses."""

from collections import Counter
from typing import Any

from acco_analysis.corpus import Agreement


def _share(n: int, total: int) -> str:
    return f"{n / total:.0%}" if total else "-"


def _stats(
    members: list[dict[str, Any]],
    by_agreement: dict[str, Agreement],
    relevance: dict[str, dict[str, Any]],
    total_agreements: int,
) -> dict[str, Any]:
    """Counts over a set of passages. An agreement with passages in several groups is
    counted once in each of them, and once in their union."""
    distinct = {
        a.id: a for a in (by_agreement[p["agreement_id"]] for p in members)
    }.values()
    return {
        "passages": len(members),
        "agreements": len(distinct),
        "share_of_agreements": round(len(distinct) / total_agreements, 3),
        "specific": sum(relevance[p["id"]]["label"] == "specific" for p in members),
        "generic": sum(relevance[p["id"]]["label"] == "generic" for p in members),
        "by_year": dict(
            sorted(Counter((a.signed or "?")[:4] for a in distinct).items())
        ),
        "top_sectors": Counter(a.sector for a in distinct if a.sector).most_common(4),
        "with_idcc": sum(bool(a.idcc) for a in distinct),
    }


def _quotes(
    label: dict[str, Any],
    by_agreement: dict[str, Agreement],
    by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    quotes = []
    for q in label.get("quotes", []):
        agreement = by_agreement[by_id[q["id"]]["agreement_id"]]
        quotes.append(
            {
                **q,
                "company": agreement.company,
                "signed": agreement.signed,
                "url": agreement.url,
            }
        )
    return quotes


def build(
    *,
    snapshot_id: str,
    agreements: list[Agreement],
    passages: list[dict[str, Any]],
    relevance: dict[str, dict[str, Any]],
    assignments: dict[str, int],
    labels: dict[int, dict[str, Any]],
    meta: dict[str, Any],
    families: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_agreement = {a.id: a for a in agreements}
    by_id = {p["id"]: p for p in passages}
    kept = [p for p in passages if p["id"] in assignments]
    kept_agreements = {p["agreement_id"] for p in kept}
    total = len(kept_agreements)

    clusters = []
    sizes = Counter(c for c in assignments.values() if c >= 0)
    for cluster_id, _ in sizes.most_common():
        members = [by_id[i] for i, c in assignments.items() if c == cluster_id]
        label = labels.get(cluster_id, {})
        clusters.append(
            {
                "cluster": cluster_id,
                **_stats(members, by_agreement, relevance, total),
                **{
                    k: label.get(k)
                    for k in ("label", "summary", "variants", "triggers", "measures")
                },
                "quotes": _quotes(label, by_agreement, by_id),
                "quotes_dropped": label.get("quotes_dropped", 0),
            }
        )

    family_rows = []
    for family in (families or {}).get("families", []):
        wanted = set(family["clusters"])
        members = [by_id[i] for i, c in assignments.items() if c in wanted]
        family_clusters = [c for c in clusters if c["cluster"] in wanted]
        family_rows.append(
            {
                **family,
                **_stats(members, by_agreement, relevance, total),
                # the verified quotes of the biggest groups, one per group
                "quotes": [
                    q
                    for c in sorted(family_clusters, key=lambda c: -c["passages"])[:3]
                    for q in c["quotes"][:1]
                ],
            }
        )

    noise = [i for i, c in assignments.items() if c == -1]
    return {
        "snapshot": snapshot_id,
        "agreements": len(agreements),
        "passages": len(passages),
        "labels": dict(Counter(r["label"] for r in relevance.values())),
        "agreements_with_a_kept_passage": len(kept_agreements),
        "clustered_passages": len(kept) - len(noise),
        "noise_passages": len(noise),
        "noise_sample": noise[:5],
        "families": family_rows,
        "families_retried": (families or {}).get("retried"),
        "families_unresolved": (families or {}).get("unresolved"),
        "clusters": clusters,
        **meta,
    }


def to_markdown(report: dict[str, Any]) -> str:
    kept = report["agreements_with_a_kept_passage"]
    out = [
        "# Heat clauses in the ACCO agreements",
        "",
        f"Snapshot `{report['snapshot']}`: {report['agreements']} agreements collected on "
        "four heat phrases (canicule, fortes chaleurs, ...), "
        f"{report['passages']} passages around a heat term.",
        "",
        "## Coverage",
        "",
        "- Passages: "
        + ", ".join(f"{n} {k}" for k, n in sorted(report["labels"].items())),
        f"- Agreements with a heat clause (specific or generic): {kept} "
        f"({_share(kept, report['agreements'])})",
        f"- Clustered: {report['clustered_passages']} passages in {len(report['clusters'])} "
        f"groups, {report['noise_passages']} left as noise",
    ]
    if "stability" in report:
        s = report["stability"]
        out.append(
            f"- Stability (adjusted Rand index, 5 subsets of 80%): mean {s['mean']}, min {s['min']}"
        )
    out += [f"- Models: {report.get('models', '')}", ""]
    if report["families"]:
        out += ["## Families", ""]
        if report.get("families_unresolved"):
            out += [
                "Grouping not fully valid after a retry, the rest was repaired: "
                + "; ".join(report["families_unresolved"]),
                "",
            ]
        for n, f in enumerate(report["families"], 1):
            groups = ", ".join(f"{i + 1}" for i in f["clusters"])
            out += [
                f"### {n}. {f['label'] or '(unlabelled)'}",
                "",
                f"{f['agreements']} agreements ({f['share_of_agreements']:.0%} of "
                f"those with a heat clause), {f['passages']} passages "
                f"({f['specific']} specific, {f['generic']} generic). "
                f"Groups: {groups}.",
                "",
                f["summary"] or "",
                "",
            ]
            for q in f["quotes"]:
                out += [
                    f"> {q['quote']}",
                    f"> — {q['company']}, {q['signed']}, [{q['id']}]({q['url']})",
                    "",
                ]
        out += ["## Groups", ""]
    for c in report["clusters"]:
        out += [
            f"{'###' if report['families'] else '##'} {c['cluster'] + 1}. "
            f"{c['label'] or '(unlabelled)'}",
            "",
            f"{c['agreements']} agreements ({c['share_of_agreements']:.0%} of those with a heat "
            f"clause), {c['passages']} passages ({c['specific']} specific, {c['generic']} generic).",
            "",
            c["summary"] or "",
            "",
        ]
        if c["variants"]:
            out += ["Variants:", ""]
            out += [
                f"- **{v.get('name', '')}**: {v.get('description', '')}"
                for v in c["variants"]
            ]
            out.append("")
        if c["triggers"]:
            out += [f"Triggers: {'; '.join(c['triggers'])}", ""]
        if c["measures"]:
            out += [f"Measures: {'; '.join(c['measures'])}", ""]
        years = ", ".join(f"{y}: {n}" for y, n in c["by_year"].items())
        sectors = "; ".join(f"{s} ({n})" for s, n in c["top_sectors"])
        out += [f"By signature year: {years}", "", f"Top sectors: {sectors}", ""]
        for q in c["quotes"]:
            out += [
                f"> {q['quote']}",
                f"> — {q['company']}, {q['signed']}, [{q['id']}]({q['url']})",
                "",
            ]
    return "\n".join(out) + "\n"
