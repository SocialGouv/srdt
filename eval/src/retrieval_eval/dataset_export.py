"""The labelled (question, document) dataset, as files.

`build_pairs` turns the pooled pairs of a run and one labeller's grades into rows;
`write_dataset` writes them with the queries, the document texts and a data card:

    pairs.jsonl / pairs.csv   one row per pooled pair: the grade (0/1/2, the only
                              label),
                              the ranks it had in each retrieval variant, and the
                              human grade when the pair is in the human gold sample
    queries.jsonl             the queries that have pairs
    documents.jsonl           the text snapshot of each document, with its hash
    README.md                 the data card

No boolean "relevant" is stored: labels are graded, and any binary reading (grade >= 1,
grade 2) is a threshold chosen when computing a metric.
"""

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from retrieval_eval.data import DocRecord, Qrel, Query, Ranking
from retrieval_eval.pipeline import K_RERANK
from retrieval_eval.pool import build_pool
from retrieval_eval.report import LabellerProfile, render_profile

PRODUCTION_VARIANT = "hybrid+rerank"
BAR = (0.6, 0.5)  # selection bar on the kappa of "useful" and "answers directly"


class DatasetError(RuntimeError):
    pass


def _column(variant: str) -> str:
    return "rank_" + variant.replace("+", "_")


@dataclass
class Dataset:
    pairs: list[dict]
    queries: list[Query]
    documents: list[DocRecord]
    variants: list[str]


def build_pairs(
    rankings: list[Ranking],
    queries: dict[str, Query],
    docs: dict[str, DocRecord],
    qrels: list[Qrel],
    labeller: str,
    depth: int,
    human: list[Qrel] | None = None,
) -> Dataset:
    """Every pooled pair at `depth`, with the labeller's grade.

    Raises DatasetError if a pooled pair has no snapshot or no grade made on that
    snapshot's text: a dataset with holes would silently bias every metric."""
    graded = {
        (q.query_id, q.doc_id, q.text_sha256): q
        for q in qrels
        if q.labeller == labeller
    }
    gold = {(q.query_id, q.doc_id, q.text_sha256): q.grade for q in (human or [])}
    variants = sorted({r.variant for r in rankings})
    rank_of = {
        (r.query_id, r.variant): {d: i for i, d in enumerate(r.doc_ids, start=1)}
        for r in rankings
    }
    pool = build_pool(rankings, depth)

    rows: list[dict] = []
    missing: list[tuple[str, str, str]] = []
    for query_id in sorted(pool):
        query = queries.get(query_id)
        if query is None:
            raise DatasetError(f"ranked query {query_id} is not in the queries file")
        for doc_id in sorted(pool[query_id]):
            doc = docs.get(doc_id)
            if doc is None:
                missing.append((query_id, doc_id, "no text snapshot"))
                continue
            key = (query_id, doc_id, doc.text_sha256)
            label = graded.get(key)
            if label is None:
                missing.append((query_id, doc_id, "not graded on this text"))
                continue
            ranks = {
                _column(v): rank_of.get((query_id, v), {}).get(doc_id) for v in variants
            }
            production = rank_of.get((query_id, PRODUCTION_VARIANT), {}).get(doc_id)
            rows.append(
                {
                    "query_id": query_id,
                    "split": query.split,
                    "doc_id": doc_id,
                    "grade": label.grade,
                    "rationale": label.rationale,
                    "labeller": label.labeller,
                    "prompt_version": label.prompt_version,
                    "prompt_sha256": label.prompt_sha256,
                    "text_sha256": doc.text_sha256,
                    **ranks,
                    "in_production_top10": production is not None
                    and production <= K_RERANK,
                    "human_grade": gold.get(key),
                    "human_gold": key in gold,
                }
            )
    if missing:
        reasons = Counter(reason for *_, reason in missing)
        raise DatasetError(
            f"{len(missing)} pooled pairs cannot be exported ({dict(reasons)}); "
            f"first: {missing[0][:2]}. Run `label` until nothing is left."
        )
    used_docs = sorted({r["doc_id"] for r in rows})
    used_queries = sorted({r["query_id"] for r in rows})
    return Dataset(
        pairs=rows,
        queries=[queries[q] for q in used_queries],
        documents=[docs[d] for d in used_docs],
        variants=variants,
    )


def _bar_status(profile: LabellerProfile) -> str:
    table = profile.table

    def kappa(section_prefix: str) -> float:
        row = table[
            table["section"].str.startswith(section_prefix)
            & (table["measure"] == "kappa")
        ].iloc[0]
        return float(row["value"])

    useful, direct = kappa("useful"), kappa("answers directly")
    passes = useful >= BAR[0] and direct >= BAR[1]
    return (
        f"kappa {useful:.2f} on 'useful' (grade >= 1) and {direct:.2f} on 'answers "
        f"directly' (grade 2), against the selection bar of {BAR[0]} and {BAR[1]}: "
        + ("**reaches the bar**." if passes else "**below the bar**.")
    )


def render_data_card(
    dataset: Dataset,
    labeller: str,
    served_model: str | None,
    prompt_version: str,
    prompt_sha: str,
    max_chars: int,
    guideline_sha: str | None,
    depth: int,
    profile: LabellerProfile | None = None,
    human_name: str | None = None,
    grade_names: dict[int, str] | None = None,
) -> str:
    names = grade_names or {}
    grades = Counter(r["grade"] for r in dataset.pairs)
    by_split = Counter(r["split"] for r in dataset.pairs)
    total = len(dataset.pairs)
    out = [
        "# Retrieval relevance dataset: (question, document) pairs graded 0/1/2",
        "",
        "Every document returned by the retrieval variants "
        f"({', '.join(f'`{v}`' for v in dataset.variants)}) in their top {depth} for "
        f"each of {len(dataset.queries)} questions, graded by a language model for how "
        "well it helps answer the question. Built to measure the search part of the "
        "SRDT RAG (Elasticsearch kNN and hybrid retrieval, then the Albert rerank), "
        "not the answers.",
        "",
        "## Labels",
        "",
        "Labels are **graded 0/1/2**; no binary label is stored. Binary readings "
        "(grade >= 1 'useful', grade 2 'answers directly') are thresholds chosen when "
        "computing a metric.",
        "",
        f"- **2**: {names.get(2, 'answers directly')}",
        f"- **1**: {names.get(1, 'useful but partial')}",
        f"- **0**: {names.get(0, 'useless')}",
        "",
        "The full definition is the guideline (`prompts/"
        + prompt_version
        + "/guideline"
        ".fr.md`)"
        + (f", sha256 starting `{guideline_sha}`." if guideline_sha else "."),
        "",
        "## How it was labelled",
        "",
        f"- Labeller: `{labeller}`"
        + (f" (served as `{served_model}`)" if served_model else "")
        + ", temperature as set in `config/labellers.toml`.",
        f"- Prompt version `{prompt_version}`, prompt hash `{prompt_sha}` (prompt "
        "files "
        f"and document length limit of {max_chars:,} characters: no document was cut).",
        "- One call per (question, document) pair, answer as JSON "
        "`{reasoning, grade}`; the reasoning is kept in `rationale`.",
        "",
        "## Contents",
        "",
        f"- `pairs.jsonl` / `pairs.csv`: {total:,} pairs. Grades: "
        + ", ".join(f"{g}: {grades[g]:,} ({grades[g] / total:.0%})" for g in (0, 1, 2))
        + ". Split: "
        + ", ".join(f"{s}: {n:,}" for s, n in sorted(by_split.items()))
        + ".",
        f"- `queries.jsonl`: {len(dataset.queries)} anonymised real user questions "
        "(`dev`/`test` split fixed when they were sampled).",
        f"- `documents.jsonl`: {len(dataset.documents)} documents "
        "(public CDTN content) with the text each grade was given and its sha256.",
        "- `rank_<variant>` is the 1-based rank the document had in that variant, "
        "empty "
        "if it did not appear; `in_production_top10` is the set the answer step reads.",
        "- `human_grade` / `human_gold`: the 120 pairs graded by hand (blind to the "
        "labeller) when `--human` was given; empty otherwise.",
        "",
    ]
    if profile is not None and human_name:
        out += [
            "## How far to trust the grades",
            "",
            "The labeller was compared with a human on a stratified sample of the "
            "pairs "
            "(figures below are weighted to estimate the whole pool of the dev "
            "questions): " + _bar_status(profile),
            "",
            render_profile(profile, labeller, human_name).replace("## ", "### ", 1),
        ]
    out += [
        "## Limits",
        "",
        "- The grades are a model's, not the truth. Absolute figures inherit its error "
        "rates (see above); comparisons between retrieval variants are less affected.",
        "- Recall measured on this dataset is relative to the pool: a relevant "
        "document "
        "that no variant retrieved is invisible.",
        "- One human annotator, with no estimate of their own consistency yet.",
        "- The human comparison covers the dev questions only; nothing independent "
        "confirms the grades on the test questions.",
        "- The questions are anonymised real user questions: keep the dataset private "
        "unless the anonymisation has been reviewed.",
        "",
    ]
    return "\n".join(out)


def write_dataset(out_dir: Path, dataset: Dataset, card: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "pairs.jsonl").open("w", encoding="utf-8") as f:
        for row in dataset.pairs:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out_dir / "pairs.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(dataset.pairs[0]))
        writer.writeheader()
        writer.writerows(dataset.pairs)
    with (out_dir / "queries.jsonl").open("w", encoding="utf-8") as f:
        for query in dataset.queries:
            f.write(
                json.dumps(query.model_dump(mode="json"), ensure_ascii=False) + "\n"
            )
    with (out_dir / "documents.jsonl").open("w", encoding="utf-8") as f:
        for doc in dataset.documents:
            f.write(json.dumps(doc.model_dump(mode="json"), ensure_ascii=False) + "\n")
    (out_dir / "README.md").write_text(card, encoding="utf-8")
