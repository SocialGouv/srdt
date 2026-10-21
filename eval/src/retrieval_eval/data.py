"""Records of the retrieval eval: queries, ranked documents, document texts, labels.

The unit that is labelled and ranked is a *document* (`metadata.id`, the cdtn id), not
a chunk: the ES chunk `_id` changes at every ingestion, the document id does not. A
label carries the sha256 of the text it was given, so that it can be told stale when
the document changes.
"""

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from judge_eval.data import dataset_sha256  # noqa: F401  (same hash for every file)
from retrieval_eval.jsonl import read_jsonl

GRADES = (0, 1, 2)
Split = Literal["dev", "test"]


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Query(BaseModel):
    """A line of `retrieval/queries.jsonl` (the split is fixed once, see queries.py)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    query_id: str
    text: str = Field(min_length=1)
    source: str
    idcc: str | None = None
    length_bucket: str = ""
    theme: str = ""
    split: Split


class DocRecord(BaseModel):
    """What a labeller is shown for a document, snapshotted at pooling time."""

    model_config = ConfigDict(extra="ignore")

    doc_id: str
    title: str = ""
    url: str = ""
    source: str = ""
    text: str
    text_sha256: str


class Ranking(BaseModel):
    """The documents a retrieval variant returned for a query, best first."""

    query_id: str
    variant: str
    doc_ids: list[str]
    # Variant-specific: ES score (kNN cosine, or RRF when hybrid), or rerank score.
    scores: list[float | None]
    # Whether the production pipeline would have added the generic `contributions`
    # collection (only when the IDCC pipeline selected nothing).
    contributions: bool = True


class Qrel(BaseModel):
    """One graded judgement of a (query, document) pair by one labeller."""

    model_config = ConfigDict(extra="ignore")

    query_id: str
    doc_id: str
    grade: int
    labeller: str  # "llm:<model name>" or "human:<name>"
    prompt_version: str = ""
    # Hash of the prompt files and of the document length limit: a label made with
    # another one is not the same experiment, whatever the version is called.
    prompt_sha256: str = ""
    text_sha256: str = ""
    rationale: str | None = None
    # Diagnostics of an LLM call; absent for a human label.
    response_mode: str | None = None
    served_model: str | None = None
    finish_reason: str | None = None
    latency_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    truncated: bool = False

    @field_validator("grade")
    @classmethod
    def _valid_grade(cls, value: int) -> int:
        if value not in GRADES:
            raise ValueError(f"grade must be one of {GRADES}, got {value}")
        return value

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.query_id, self.doc_id, self.labeller, self.text_sha256)


def load_queries(path: Path, split: Split | None = None) -> list[Query]:
    queries = list(read_jsonl(path, Query))
    ids = [q.query_id for q in queries]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"{path}: duplicate query ids {dupes[:5]}")
    return [q for q in queries if split is None or q.split == split]


def load_docs(path: Path) -> dict[str, DocRecord]:
    """Latest snapshot of each document."""
    return {d.doc_id: d for d in read_jsonl(path, DocRecord)}


def load_rankings(path: Path) -> list[Ranking]:
    """Latest ranking per (query, variant)."""
    latest = {(r.query_id, r.variant): r for r in read_jsonl(path, Ranking)}
    return list(latest.values())


def load_qrels(*paths: Path) -> list[Qrel]:
    """Latest record per (query, document, labeller, text hash) across the files."""
    latest: dict[tuple[str, str, str, str], Qrel] = {}
    for path in paths:
        for qrel in read_jsonl(path, Qrel):
            latest[qrel.key] = qrel
    return list(latest.values())


def grades_by_query(
    qrels: list[Qrel], labeller: str | None = None
) -> dict[str, dict[str, int]]:
    """{query_id: {doc_id: grade}} for one labeller (all if None; the last one wins).

    A document labelled twice by the same labeller with different texts keeps the
    last record: filter on `text_sha256` first if that matters.
    """
    out: dict[str, dict[str, int]] = {}
    for q in qrels:
        if labeller is None or q.labeller == labeller:
            out.setdefault(q.query_id, {})[q.doc_id] = q.grade
    return out
