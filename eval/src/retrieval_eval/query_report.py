"""A report on one question: what each retrieval variant returned, how the labeller
graded it, and which useful documents production did not put in its top ten.

Grades are the 0/1/2 of the labeller (and the human's, when given); metrics use the
usual thresholds (grade >= 1, grade 2) and are those of `report`, for this query alone.
"""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from retrieval_eval.data import DocRecord, Query, Ranking
from retrieval_eval.metrics import Grades, query_metrics
from retrieval_eval.pipeline import K_RERANK

PRODUCTION = "hybrid+rerank"
VARIANT_ORDER = ("hybrid+rerank", "hybrid", "knn")


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def find_queries(queries: Sequence[Query], text: str) -> list[Query]:
    """Queries whose id starts with `text` or whose text contains it (accents and case
    ignored)."""
    needle = _plain(text)
    return [
        q for q in queries if q.query_id.startswith(text) or needle in _plain(q.text)
    ]


@dataclass(frozen=True)
class Weakness:
    query_id: str
    ndcg: float
    precision: float
    recall: float
    relevant: int  # documents graded >= 1 in the pool


def worst_queries(
    rankings: list[Ranking],
    grades: dict[str, Grades],
    n: int,
    variant: str = PRODUCTION,
    k: int = K_RERANK,
) -> list[Weakness]:
    """The `n` queries on which `variant` scores the lowest nDCG@k, among those with at
    least one useful document (without one nothing can be missed)."""
    out = []
    for ranking in rankings:
        if ranking.variant != variant or not grades.get(ranking.query_id):
            continue
        g = grades[ranking.query_id]
        if not any(v >= 1 for v in g.values()):
            continue
        m = query_metrics(ranking.doc_ids, g, [k])
        out.append(
            Weakness(
                ranking.query_id,
                m[f"ndcg@{k}"],
                m[f"precision@{k}(>=1)"],
                m[f"recall@{k}(>=1)"],
                sum(v >= 1 for v in g.values()),
            )
        )
    return sorted(out, key=lambda w: (w.ndcg, w.query_id))[:n]


def _clip(text: str | None, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _cell(text: str) -> str:
    return text.replace("|", "/")


def render_query_report(
    query: Query,
    rankings: list[Ranking],
    docs: dict[str, DocRecord],
    grades: Grades,
    rationales: dict[str, str | None],
    human: Grades | None = None,
    k: int = K_RERANK,
    rationale_chars: int = 200,
    missed_limit: int = 15,
) -> str:
    by_variant = {r.variant: r for r in rankings if r.query_id == query.query_id}
    if PRODUCTION not in by_variant:
        raise ValueError(f"query {query.query_id} has no {PRODUCTION} ranking")
    production = by_variant[PRODUCTION]
    variants = [v for v in VARIANT_ORDER if v in by_variant] + sorted(
        set(by_variant) - set(VARIANT_ORDER)
    )

    def rank_in(variant: str, doc_id: str) -> str:
        ranking = by_variant.get(variant)
        if ranking is None or doc_id not in ranking.doc_ids:
            return "-"
        return str(ranking.doc_ids.index(doc_id) + 1)

    def grade_of(doc_id: str) -> str:
        return str(grades[doc_id]) if doc_id in grades else "?"

    useful = {d for d, g in grades.items() if g >= 1}
    out = [
        f"# Question {query.query_id}",
        "",
        f"> {_clip(query.text, 1500)}",
        "",
        f"split `{query.split}`, length `{query.length_bucket or '-'}`, "
        f"IDCC {query.idcc or 'none'}. Grades are the labeller's (0 useless, 1 useful "
        "but partial, 2 answers directly)"
        + ("; `you` is the human grade." if human else "."),
        "",
        f"The pool holds {len(grades)} graded documents for this question: "
        f"{sum(g == 2 for g in grades.values())} graded 2, "
        f"{sum(g == 1 for g in grades.values())} graded 1, "
        f"{sum(g == 0 for g in grades.values())} graded 0.",
        "",
        "## How each variant did on this question",
        "",
    ]
    rows = []
    for variant in variants:
        m = query_metrics(by_variant[variant].doc_ids, grades, [k])
        rows.append(
            [
                f"**{variant}**" if variant == PRODUCTION else variant,
                f"{m[f'precision@{k}(>=1)']:.2f}",
                f"{m[f'recall@{k}(>=1)']:.2f}",
                f"{m[f'ndcg@{k}']:.2f}",
                f"{m['mrr(>=1)']:.2f}",
                f"{m[f'recall@{k}(>=2)']:.2f}",
            ]
        )
    out += [
        _table(
            [
                "variant",
                f"precision@{k} (>=1)",
                f"recall@{k} (>=1)",
                f"nDCG@{k}",
                "MRR (>=1)",
                f"recall@{k} (grade 2)",
            ],
            rows,
        ),
        "",
        "Recall is relative to the pool. 'nan' means no document reaches that grade "
        "for this question.",
        "",
        f"## What production sends to the answer step (top {k} of `{PRODUCTION}`)",
        "",
    ]
    shown = production.doc_ids[:k]
    header = [
        "#",
        "grade",
        *(["you"] if human else []),
        "document",
        "source",
        "hybrid",
        "kNN",
    ]
    rows = []
    for rank, doc_id in enumerate(shown, start=1):
        doc = docs.get(doc_id)
        rows.append(
            [
                str(rank),
                grade_of(doc_id),
                *([str(human[doc_id]) if doc_id in human else "-"] if human else []),
                _cell(_clip(doc.title if doc else doc_id, 70)),
                _cell(doc.source if doc else "?"),
                rank_in("hybrid", doc_id),
                rank_in("knn", doc_id),
            ]
        )
    out += [_table(header, rows), ""]

    out += ["### Why the labeller graded them so", ""]
    for rank, doc_id in enumerate(shown, start=1):
        doc = docs.get(doc_id)
        title = _clip(doc.title if doc else doc_id, 80)
        out.append(
            f"{rank}. **{grade_of(doc_id)}** {title}: "
            f"{_clip(rationales.get(doc_id), rationale_chars) or '(no rationale)'}"
        )
    out.append("")

    missed = sorted(
        (d for d in useful if d not in shown),
        key=lambda d: (-grades[d], _first_rank(by_variant, d), d),
    )
    out += [f"## Useful documents production did not send ({len(missed)})", ""]
    if not missed:
        out += [f"None: every document graded 1 or 2 is in its top {k}.", ""]
    else:
        header = [
            "grade",
            *(["you"] if human else []),
            "document",
            "source",
            f"`{PRODUCTION}`",
            "hybrid",
            "kNN",
        ]
        rows = [
            [
                grade_of(d),
                *([str(human[d]) if d in human else "-"] if human else []),
                _cell(_clip(docs[d].title if d in docs else d, 70)),
                _cell(docs[d].source if d in docs else "?"),
                rank_in(PRODUCTION, d),
                rank_in("hybrid", d),
                rank_in("knn", d),
            ]
            for d in missed[:missed_limit]
        ]
        out += [_table(header, rows), ""]
        if len(missed) > missed_limit:
            out += [f"({len(missed) - missed_limit} more not shown.)", ""]
    return "\n".join(out)


def _first_rank(by_variant: dict[str, Ranking], doc_id: str) -> int:
    ranks = [
        r.doc_ids.index(doc_id) + 1 for r in by_variant.values() if doc_id in r.doc_ids
    ]
    return min(ranks) if ranks else 10**6


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def render_weaknesses(
    weaknesses: Sequence[Weakness], queries: dict[str, Query], variant: str = PRODUCTION
) -> str:
    rows = []
    for w in weaknesses:
        q = queries[w.query_id]
        rows.append(
            [
                w.query_id,
                q.split,
                q.idcc or "-",
                f"{w.ndcg:.2f}",
                f"{w.precision:.2f}",
                f"{w.recall:.2f}",
                str(w.relevant),
                _cell(_clip(q.text, 90)),
            ]
        )
    return "\n".join(
        [
            f"Lowest nDCG@{K_RERANK} for `{variant}`, among questions with at least "
            "one useful document:",
            "",
            _table(
                [
                    "query id",
                    "split",
                    "IDCC",
                    "nDCG",
                    "precision",
                    "recall",
                    "useful docs",
                    "question",
                ],
                rows,
            ),
        ]
    )
