"""Run the retrieval variants over the queries and snapshot the documents found.

runs/<run_id>/
    config.json      queries hash and search settings
    rankings.jsonl   one line per (query, variant): the ranked document ids
    docs.jsonl       full text of the documents pooled for labelling, one per document

Resumable: queries whose variants are all stored are skipped, and documents already in
docs.jsonl are not fetched again. The pool of a query (the documents to label) is
derived from the rankings with `build_pool`: its depth is a labelling-time decision.
"""

import asyncio
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from retrieval_eval.data import (
    DocRecord,
    Query,
    Ranking,
    load_docs,
    load_rankings,
    text_sha256,
)
from retrieval_eval.jsonl import append_jsonl
from retrieval_eval.pipeline import VARIANTS, rank_query
from retrieval_eval.search_client import SearchAPI, SearchAPIError

RANKINGS_FILE = "rankings.jsonl"
DOCS_FILE = "docs.jsonl"
CONFIG_FILE = "config.json"
RETRIEVE_BATCH = 10  # the web asks for ten documents at a time; the route caps chunks


class PoolConfigError(RuntimeError):
    pass


@dataclass
class PoolSummary:
    ranked: int = 0
    skipped: int = 0
    failed: dict[str, str] = field(default_factory=dict)  # query_id -> error
    docs_fetched: int = 0
    docs_missing: list[str] = field(default_factory=list)


def check_pool_config(
    run_dir: Path, *, queries_sha256: str, top_k: int, variants: list[str]
) -> None:
    """Create or update config.json; refuse to mix results from different setups."""
    path = run_dir / CONFIG_FILE
    config = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "queries_sha256": queries_sha256,
        "top_k": top_k,
        "variants": sorted(variants),
    }
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        for name in ("queries_sha256", "top_k"):
            if existing[name] != config[name]:
                raise PoolConfigError(
                    f"{path}: {name} differs from this run's setup "
                    f"({existing[name]!r} vs {config[name]!r}). "
                    "Use a new --run-id instead of mixing results."
                )
        config["created_at"] = existing["created_at"]
        config["variants"] = sorted(set(existing["variants"]) | set(variants))
    run_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def build_pool(rankings: list[Ranking], depth: int) -> dict[str, dict[str, list[str]]]:
    """{query_id: {doc_id: ["variant@rank", ...]}}: the union of each variant's top
    `depth` documents, in first-seen order, with where each was found (1-based)."""
    pool: dict[str, dict[str, list[str]]] = {}
    for ranking in rankings:
        found = pool.setdefault(ranking.query_id, {})
        for rank, doc_id in enumerate(ranking.doc_ids[:depth], start=1):
            found.setdefault(doc_id, []).append(f"{ranking.variant}@{rank}")
    return pool


async def rank_queries(
    api: SearchAPI,
    queries: list[Query],
    run_dir: Path,
    *,
    variants: list[str],
    top_k: int,
    concurrency: int = 4,
    on_progress: Callable[[int, int], None] | None = None,
) -> PoolSummary:
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown:
        raise ValueError(f"unknown variants {unknown}; known: {sorted(VARIANTS)}")
    path = run_dir / RANKINGS_FILE
    done = {(r.query_id, r.variant) for r in load_rankings(path)}
    summary = PoolSummary()
    todo = []
    for query in queries:
        missing = [v for v in variants if (query.query_id, v) not in done]
        if missing:
            todo.append((query, missing))
        else:
            summary.skipped += 1

    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    finished = 0

    async def one(query: Query, missing: list[str]) -> None:
        nonlocal finished
        async with semaphore:
            try:
                rankings = await rank_query(api, query, missing, top_k)
            except SearchAPIError as e:
                summary.failed[query.query_id] = str(e)
                return
        async with lock:
            append_jsonl(path, rankings)
            summary.ranked += 1
            finished += 1
            if on_progress:
                on_progress(finished, len(todo))

    await asyncio.gather(*(one(q, m) for q, m in todo))
    return summary


async def fetch_docs(
    api: SearchAPI,
    run_dir: Path,
    *,
    depth: int,
    concurrency: int = 4,
) -> tuple[int, list[str]]:
    """Fetch the text of every document in the top `depth` of any stored ranking.
    Returns (fetched, ids the API did not return)."""
    path = run_dir / DOCS_FILE
    wanted: list[str] = []
    for found in build_pool(load_rankings(run_dir / RANKINGS_FILE), depth).values():
        wanted.extend(found)
    have = set(load_docs(path))
    todo = [d for d in dict.fromkeys(wanted) if d not in have]
    batches = [
        todo[i : i + RETRIEVE_BATCH] for i in range(0, len(todo), RETRIEVE_BATCH)
    ]

    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    fetched = 0
    missing: list[str] = []

    async def one(batch: list[str]) -> None:
        nonlocal fetched
        async with semaphore:
            contents = await api.retrieve(batch)
        records = []
        for content in contents:
            meta = content["metadata"]
            text = content["content"]
            records.append(
                DocRecord(
                    doc_id=meta["id"],
                    title=meta.get("title", ""),
                    url=meta.get("url", ""),
                    source=meta.get("source", ""),
                    text=text,
                    text_sha256=text_sha256(text),
                )
            )
        async with lock:
            append_jsonl(path, records)
            fetched += len(records)
            returned = {r.doc_id for r in records}
            missing.extend(d for d in batch if d not in returned)

    await asyncio.gather(*(one(b) for b in batches))
    return fetched, missing


def describe_rankings(rankings: list[Ranking], depth: int) -> str:
    """Pool sizes and overlap between variants, for a quick look before labelling."""
    pool = build_pool(rankings, depth)
    sizes = sorted(len(found) for found in pool.values())
    by_variant = Counter(r.variant for r in rankings)
    lines = [
        f"{len(pool)} queries, rankings per variant: "
        f"{dict(sorted(by_variant.items()))}",
    ]
    if sizes:
        lines.append(
            f"pool at depth {depth}: {sum(sizes)} (query, document) pairs, "
            f"per query min {sizes[0]} / median {sizes[len(sizes) // 2]} "
            f"/ max {sizes[-1]}"
        )
    return "\n".join(lines)
