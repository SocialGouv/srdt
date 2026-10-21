"""Blind human labelling sheets.

Two ways to draw the (query, document) pairs a human labels:
- `sample_audit`: among the LLM-labelled pairs, stratified by LLM grade and by whether
  production put the document in its top K_RERANK. Audits a chosen labeller.
- `sample_pool_pairs`: among the pooled pairs, stratified by retrieval provenance only.
  No model is involved, so it can serve to compare models.
- `sample_screened_pairs`: among the pooled pairs, stratified by what a few fast
  "screener" models graded, so that the pairs worth a human's time (the relevant ones,
  the disputed ones) are not drowned in obvious zeros. The human still labels blind;
  every pair carries the weight of its stratum so that the estimates describe the pool.

`export_sheet` writes what the annotator sees (no LLM grade, no rationale) and a
separate key; the annotator fills `grade` (0/1/2) and `import_sheet` turns the rows
into human qrels. `subset_items` redraws a few pairs under fresh ids for a second,
blind pass.
"""

import csv
import json
import random
from collections import defaultdict
from collections.abc import Callable, Hashable, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from retrieval_eval.data import GRADES, DocRecord, Qrel, Query, Ranking
from retrieval_eval.pipeline import K_RERANK
from retrieval_eval.pool import build_pool

PRODUCTION_VARIANT = "hybrid+rerank"
MAX_CELL_CHARS = 30000  # a spreadsheet cell holds at most 32767
CONTINUATION_COLUMNS = ("document_2", "document_3", "document_4")
# What a sheet can show: the comparison labels with `--max-chars` set to this, so that
# the human and the models read the same text.
SHEET_MAX_CHARS = MAX_CELL_CHARS * (1 + len(CONTINUATION_COLUMNS))
SHEET_FIELDS = [
    "audit_id",
    "query",
    "idcc",
    "title",
    "source",
    "url",
    "document",
    "grade",
    "comment",
    *CONTINUATION_COLUMNS,
]


class AuditError(ValueError):
    pass


@dataclass(frozen=True)
class AuditItem:
    audit_id: str
    query_id: str
    doc_id: str
    text_sha256: str
    in_production_top: bool
    llm_grade: int | None = None  # None when no model was involved in the draw
    # Set by `sample_screened_pairs`: the stratum and how many pool pairs this pair
    # stands for (1.0 when the draw was not stratified). Never shown to the annotator.
    stratum: str | None = None
    weight: float = 1.0


def _allocate_equal(sizes: dict[tuple, int], n: int) -> dict[tuple, int]:
    """Equal share per cell, capped by the cell size; the shortfall of small cells
    goes to the others."""
    quota = dict.fromkeys(sizes, 0)
    open_cells = {c for c, size in sizes.items() if size > 0}
    remaining = min(n, sum(sizes.values()))
    while remaining > 0 and open_cells:
        share = max(remaining // len(open_cells), 1)
        for cell in sorted(open_cells):
            take = min(share, sizes[cell] - quota[cell], remaining)
            quota[cell] += take
            remaining -= take
            if quota[cell] >= sizes[cell]:
                open_cells.discard(cell)
            if remaining == 0:
                break
    return quota


def _stratified_pick[T](
    items: list[T],
    cell_of: Callable[[T], Hashable],
    query_of: Callable[[T], str],
    n: int,
    per_query_cap: int,
    rng: random.Random,
) -> list[T]:
    """Up to `n` items, an equal share per cell, at most `per_query_cap` per query
    (the items of one query are correlated). Returned in random order.

    Quotas come from the uncapped cell sizes, then the cap is applied while drawing,
    smallest cell first: capping first would starve the rare cells (e.g. documents
    production did not rank in its top K, which show pool gaps). What a cell cannot
    give under the cap is spread over the others. `items` should already be in a
    random order: each cell is taken from its start."""
    cells: dict[Hashable, list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        cells[cell_of(item)].append(index)

    picked: list[int] = []
    chosen: set[int] = set()
    taken: dict[str, int] = defaultdict(int)
    while len(picked) < n:
        available = {
            cell: [
                i
                for i in indexes
                if i not in chosen and taken[query_of(items[i])] < per_query_cap
            ]
            for cell, indexes in cells.items()
        }
        quota = _allocate_equal(
            {(c,): len(a) for c, a in available.items()}, n - len(picked)
        )
        before = len(picked)
        for cell in sorted(available, key=lambda c: len(available[c])):
            for i in available[cell][: quota[(cell,)]]:
                query = query_of(items[i])
                if taken[query] < per_query_cap:
                    taken[query] += 1
                    chosen.add(i)
                    picked.append(i)
        if len(picked) == before:
            break
    rng.shuffle(picked)
    return [items[i] for i in picked]


def sample_audit(
    llm_qrels: list[Qrel],
    rankings: list[Ranking],
    n: int,
    seed: int,
    *,
    query_ids: set[str] | None = None,
    per_query_cap: int = 3,
    production_variant: str = PRODUCTION_VARIANT,
) -> list[AuditItem]:
    """Stratified sample of at most `n` LLM-labelled pairs, at most `per_query_cap`
    per query (the pairs of one query are correlated)."""
    production_top = _production_top(rankings, production_variant)
    rng = random.Random(seed)
    candidates = sorted(
        (q for q in llm_qrels if query_ids is None or q.query_id in query_ids),
        key=lambda q: (q.query_id, q.doc_id),
    )
    rng.shuffle(candidates)
    picked = _stratified_pick(
        candidates,
        cell_of=lambda q: (q.grade, (q.query_id, q.doc_id) in production_top),
        query_of=lambda q: q.query_id,
        n=n,
        per_query_cap=per_query_cap,
        rng=rng,
    )
    return [
        AuditItem(
            audit_id=f"a{index:04d}",
            query_id=q.query_id,
            doc_id=q.doc_id,
            text_sha256=q.text_sha256,
            in_production_top=(q.query_id, q.doc_id) in production_top,
            llm_grade=q.grade,
        )
        for index, q in enumerate(picked, start=1)
    ]


def _production_top(
    rankings: list[Ranking], variant: str = PRODUCTION_VARIANT
) -> set[tuple[str, str]]:
    return {
        (r.query_id, d)
        for r in rankings
        if r.variant == variant
        for d in r.doc_ids[:K_RERANK]
    }


def sample_pool_pairs(
    rankings: list[Ranking],
    docs: dict[str, DocRecord],
    query_ids: set[str],
    depth: int,
    n: int,
    seed: int,
    *,
    per_query_cap: int = 3,
    production_variant: str = PRODUCTION_VARIANT,
) -> list[AuditItem]:
    """Stratified sample of at most `n` pooled pairs, from retrieval provenance alone:
    in production's top K_RERANK or not, found by one variant or by several. No
    label, from a model or a human, is read, so every candidate labeller can be
    compared on the result. Pairs without a stored document text are left out."""
    production_top = _production_top(rankings, production_variant)
    pool = build_pool(rankings, depth)
    rng = random.Random(seed)
    candidates = [
        (query_id, doc_id, len({f.split("@")[0] for f in found}))
        for query_id in sorted(query_ids & pool.keys())
        for doc_id, found in sorted(pool[query_id].items())
        if doc_id in docs
    ]
    rng.shuffle(candidates)
    picked = _stratified_pick(
        candidates,
        cell_of=lambda c: ((c[0], c[1]) in production_top, c[2] > 1),
        query_of=lambda c: c[0],
        n=n,
        per_query_cap=per_query_cap,
        rng=rng,
    )
    return [
        AuditItem(
            audit_id=f"a{index:04d}",
            query_id=query_id,
            doc_id=doc_id,
            text_sha256=docs[doc_id].text_sha256,
            in_production_top=(query_id, doc_id) in production_top,
        )
        for index, (query_id, doc_id, _) in enumerate(picked, start=1)
    ]


STRATA = (
    "consensus-relevant",  # every screener >= 1, at least one says 2
    "consensus-partial",  # every screener >= 1, none says 2
    "disputed",  # some screeners >= 1, some 0
    "consensus-irrelevant",  # every screener says 0
)
DEFAULT_SHARES = {
    "consensus-relevant": 0.25,
    "consensus-partial": 0.17,
    "disputed": 0.33,
    "consensus-irrelevant": 0.25,
}


def screening_stratum(grades: Sequence[int]) -> str:
    useful = [g >= 1 for g in grades]
    if all(useful):
        return "consensus-relevant" if max(grades) == 2 else "consensus-partial"
    return "disputed" if any(useful) else "consensus-irrelevant"


@dataclass(frozen=True)
class StratumInfo:
    pool: int  # pool pairs in the stratum
    sampled: int
    weight: float  # pool / sampled: pool pairs each sampled pair stands for


@dataclass
class ScreenedSample:
    items: list[AuditItem]
    strata: dict[str, StratumInfo]
    unscreened: int  # pool pairs some screener did not grade: left out


def default_allocation(n: int) -> dict[str, int]:
    """`n` split over the strata by DEFAULT_SHARES (largest remainders)."""
    raw = {s: DEFAULT_SHARES[s] * n for s in STRATA}
    alloc = {s: int(v) for s, v in raw.items()}
    for s in sorted(STRATA, key=lambda s: raw[s] - alloc[s], reverse=True)[
        : n - sum(alloc.values())
    ]:
        alloc[s] += 1
    return alloc


def sample_screened_pairs(
    rankings: list[Ranking],
    docs: dict[str, DocRecord],
    screeners: dict[str, list[Qrel]],
    query_ids: set[str],
    depth: int,
    n: int,
    seed: int,
    *,
    allocation: dict[str, int] | None = None,
    production_variant: str = PRODUCTION_VARIANT,
) -> ScreenedSample:
    """Stratified random sample of the pool, strata given by the screeners' grades.

    Within a stratum every pair has the same chance of being drawn, so a drawn pair
    stands for `pool / sampled` pairs of its stratum (`weight`): weighted statistics
    estimate the pool's, whatever the allocation. Pairs the screeners all graded 0 are
    still sampled (a few), to measure what the screeners miss. Only pairs graded by
    every screener are eligible. There is no per-query cap: it would make the
    weights uneven, and the bootstrap over queries already accounts for the
    correlation of the pairs of one query."""
    if not screeners:
        raise ValueError("no screener labels")
    allocation = allocation or default_allocation(n)
    unknown = set(allocation) - set(STRATA)
    if unknown:
        raise ValueError(f"unknown strata {sorted(unknown)}; known: {list(STRATA)}")
    production_top = _production_top(rankings, production_variant)
    graded = [
        {(q.query_id, q.doc_id, q.text_sha256): q.grade for q in qrels}
        for qrels in screeners.values()
    ]
    pool = build_pool(rankings, depth)
    rng = random.Random(seed)

    members: dict[str, list[tuple[str, str]]] = {s: [] for s in STRATA}
    unscreened = 0
    for query_id in sorted(query_ids & pool.keys()):
        for doc_id in sorted(pool[query_id]):
            doc = docs.get(doc_id)
            if doc is None:
                continue
            key = (query_id, doc_id, doc.text_sha256)
            if any(key not in g for g in graded):
                unscreened += 1
                continue
            members[screening_stratum([g[key] for g in graded])].append(
                (query_id, doc_id)
            )

    items: list[AuditItem] = []
    strata: dict[str, StratumInfo] = {}
    for stratum in STRATA:
        pairs = members[stratum]
        rng.shuffle(pairs)
        drawn = pairs[: min(allocation.get(stratum, 0), len(pairs))]
        weight = len(pairs) / len(drawn) if drawn else 0.0
        strata[stratum] = StratumInfo(len(pairs), len(drawn), weight)
        for query_id, doc_id in drawn:
            items.append(
                AuditItem(
                    audit_id="",
                    query_id=query_id,
                    doc_id=doc_id,
                    text_sha256=docs[doc_id].text_sha256,
                    in_production_top=(query_id, doc_id) in production_top,
                    stratum=stratum,
                    weight=weight,
                )
            )
    rng.shuffle(items)
    items = [replace(item, audit_id=f"a{i:04d}") for i, item in enumerate(items, 1)]
    return ScreenedSample(items, strata, unscreened)


def load_key(path: Path) -> list[AuditItem]:
    return [AuditItem(**i) for i in json.loads(path.read_text(encoding="utf-8"))]


def subset_items(
    items: Sequence[AuditItem], n: int, seed: int, id_prefix: str = "b"
) -> list[AuditItem]:
    """A random subset of `n` items under fresh ids and in a new order, so that a
    second pass over them is not guided by the ids or the order of the first."""
    rng = random.Random(seed)
    chosen = rng.sample(list(items), min(n, len(items)))
    return [
        replace(item, audit_id=f"{id_prefix}{index:04d}")
        for index, item in enumerate(chosen, start=1)
    ]


def split_document(text: str) -> dict[str, str]:
    """The text over the `document` column and its continuation columns, in pieces of
    at most MAX_CELL_CHARS (a cell cannot hold more), each but the last ending with a
    pointer to the next column. Beyond SHEET_MAX_CHARS the end is cut and says so."""
    columns = ("document", *CONTINUATION_COLUMNS)
    cut = len(text) > SHEET_MAX_CHARS
    pieces = [
        text[i : i + MAX_CELL_CHARS] for i in range(0, SHEET_MAX_CHARS, MAX_CELL_CHARS)
    ]
    out = dict.fromkeys(columns, "")
    for index, (column, piece) in enumerate(zip(columns, pieces, strict=True)):
        if not piece:
            break
        last = index == len(columns) - 1 or not text[(index + 1) * MAX_CELL_CHARS :]
        if last and cut and index == len(columns) - 1:
            piece += "\n[… document tronqué dans cette feuille]"
        elif not last:
            piece += f"\n[… suite dans la colonne {columns[index + 1]}]"
        out[column] = piece
    return out


def export_sheet(
    items: list[AuditItem],
    queries: dict[str, Query],
    docs: dict[str, DocRecord],
    sheet_path: Path,
    key_path: Path,
) -> int:
    """Write the blind CSV and the key. Returns the number of rows written; pairs
    whose document text was not snapshotted are left out of both."""
    rows, kept = [], []
    for item in items:
        doc = docs.get(item.doc_id)
        if doc is None or doc.text_sha256 != item.text_sha256:
            continue
        query = queries[item.query_id]
        rows.append(
            {
                "audit_id": item.audit_id,
                "query": query.text,
                "idcc": query.idcc or "",
                "title": doc.title,
                "source": doc.source,
                "url": doc.url,
                "grade": "",
                "comment": "",
                **split_document(doc.text),
            }
        )
        kept.append(item)
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    with sheet_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    key_path.write_text(
        json.dumps([asdict(i) for i in kept], indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    return len(rows)


def import_sheet(
    sheet_path: Path, key_path: Path, annotator: str, guideline_version: str
) -> tuple[list[Qrel], int]:
    """Human qrels from a filled sheet, and the number of rows left blank.

    Raises AuditError on an unknown `audit_id` or a grade outside 0/1/2: a typo in
    a label is worth stopping for."""
    key = {i["audit_id"]: i for i in json.loads(key_path.read_text(encoding="utf-8"))}
    qrels: list[Qrel] = []
    blank = 0
    with sheet_path.open(newline="", encoding="utf-8") as f:
        for number, row in enumerate(csv.DictReader(f), start=2):
            raw = (row.get("grade") or "").strip()
            if not raw:
                blank += 1
                continue
            item = key.get(row["audit_id"])
            if item is None:
                raise AuditError(f"{sheet_path}:{number}: unknown {row['audit_id']!r}")
            if raw not in {str(g) for g in GRADES}:
                raise AuditError(
                    f"{sheet_path}:{number}: grade {raw!r} is not one of {GRADES}"
                )
            qrels.append(
                Qrel(
                    query_id=item["query_id"],
                    doc_id=item["doc_id"],
                    grade=int(raw),
                    labeller=f"human:{annotator}",
                    prompt_version=guideline_version,
                    text_sha256=item["text_sha256"],
                    rationale=(row.get("comment") or "").strip() or None,
                )
            )
    return qrels, blank
