"""LLM graded relevance labels (0/1/2) of (query, document) pairs.

Reuses the judge-eval plumbing (model config, OpenAI-compatible client, the
json_schema -> json_object -> prompt fallback) with its own prompt book, JSON schema
and parser. Labels go to a qrels file (`Qrel` per line); a pair that could not be
labelled goes to a sidecar `<qrels>.failures.jsonl`.
"""

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from judge_eval.endpoints import check_models, make_client
from judge_eval.judge import (
    _CODE_FENCE,
    _THINK_BLOCK,
    ModelConfig,
    OpenAICompatibleJudge,
    ParseError,
    Verdict,
    _json_objects,
    describe_error,
)
from retrieval_eval.audit import AuditItem
from retrieval_eval.data import DocRecord, Qrel, Query, load_qrels, text_sha256
from retrieval_eval.jsonl import append_jsonl, read_jsonl

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
TRUNCATION_MARK = "\n\n[… document tronqué]"
DEFAULT_MAX_CHARS = 12000

GRADE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "grade",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
                "grade": {"type": "integer", "enum": [0, 1, 2]},
            },
            "required": ["reasoning", "grade"],
            "additionalProperties": False,
        },
    },
}


def _read(path: Path) -> str:
    # HTML comments are notes for maintainers and are not sent to the model.
    return _HTML_COMMENT.sub("", path.read_text(encoding="utf-8")).strip()


class LabelPromptBook:
    """Prompts of one version: `<root>/<version>/{system,guideline,user}.fr.md`."""

    FILES = ("system", "guideline", "user")

    def __init__(self, root: Path, version: str, max_chars: int = DEFAULT_MAX_CHARS):
        directory = root / version
        if not directory.is_dir():
            raise FileNotFoundError(f"Prompt version not found: {directory}")
        self.version = version
        self.max_chars = max_chars
        paths = {name: directory / f"{name}.fr.md" for name in self.FILES}
        self._text = {name: _read(path) for name, path in paths.items()}
        digest = hashlib.sha256()
        for name in sorted(paths):
            digest.update(paths[name].read_bytes())
        digest.update(str(max_chars).encode())
        self.sha256 = digest.hexdigest()

    def render(self, query: Query, doc: DocRecord) -> tuple[list[dict[str, str]], bool]:
        """Chat messages, and whether the document was cut to `max_chars`."""
        text = doc.text.strip()
        truncated = len(text) > self.max_chars
        if truncated:
            text = text[: self.max_chars].rstrip() + TRUNCATION_MARK
        idcc_line = (
            f"\nConvention collective de l'usager (IDCC) : {query.idcc}\n"
            if query.idcc
            else ""
        )
        system = f"{self._text['system']}\n\n{self._text['guideline']}"
        user = self._text["user"].format(
            question=query.text.strip(),
            idcc_line=idcc_line,
            title=doc.title.strip() or "(sans titre)",
            source=doc.source or "(inconnue)",
            document=text,
        )
        return (
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            truncated,
        )


class Grading(Verdict):
    """Outcome of one labelling call; `grade` is None unless status is ok."""

    grade: int | None = None


class GradeOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reasoning: str = ""
    grade: int


_GRADE_FIELD = re.compile(r'"grade"\s*:\s*"?([012])"?')


def _to_grade(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and value.strip() in {"0", "1", "2"}:
        value = int(value)
    return value if isinstance(value, int) and value in (0, 1, 2) else None


def parse_grade(text: str) -> GradeOutput:
    """Extract {"reasoning", "grade"} from a reply, tolerating prose, code fences,
    <think> blocks and truncated JSON. A grade is never guessed from free text."""
    cleaned = _THINK_BLOCK.sub("", text).strip()
    fenced = _CODE_FENCE.search(cleaned)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(cleaned)

    rejected: str | None = None
    for candidate in candidates:
        for obj in _json_objects(candidate):
            if "grade" not in obj:
                continue
            grade = _to_grade(obj["grade"])
            if grade is None:
                rejected = f"unrecognised grade {obj['grade']!r}"
                continue
            reasoning = obj.get("reasoning")
            return GradeOutput(
                grade=grade, reasoning=reasoning if isinstance(reasoning, str) else ""
            )

    field_match = _GRADE_FIELD.search(cleaned)  # JSON cut after the grade field
    if field_match:
        return GradeOutput(grade=int(field_match.group(1)))
    raise ParseError(rejected or "no JSON object with a 'grade' field found")


class GradeLabeller(OpenAICompatibleJudge):
    """Labeller backed by any /v1/chat/completions endpoint."""

    response_schema = GRADE_SCHEMA

    def __init__(
        self,
        config: ModelConfig,
        prompts: LabelPromptBook,
        client: AsyncOpenAI | None = None,
    ):
        super().__init__(config, None, client)  # type: ignore[arg-type]
        self.label_prompts = prompts
        self.labeller = f"llm:{config.name}"

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "prompt_version": self.label_prompts.version,
            "prompt_sha256": self.label_prompts.sha256,
            "max_chars": self.label_prompts.max_chars,
        }

    async def grade(self, query: Query, doc: DocRecord) -> tuple[Grading, bool]:
        """The grading and whether the document was truncated in the prompt."""
        messages, truncated = self.label_prompts.render(query, doc)
        started = time.perf_counter()
        try:
            completion, mode = await self._complete(messages)
        except openai.OpenAIError as e:
            return (
                Grading(
                    status="api_error",
                    error=describe_error(e),
                    latency_s=time.perf_counter() - started,
                ),
                truncated,
            )
        usage = completion.usage
        common = {
            "response_mode": mode,
            "served_model": completion.model,
            "latency_s": time.perf_counter() - started,
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
        }
        if not completion.choices:
            return (
                Grading(status="api_error", error="response has no choices", **common),
                truncated,
            )
        choice = completion.choices[0]
        text = choice.message.content or ""
        common["finish_reason"] = choice.finish_reason
        try:
            parsed = parse_grade(text)
        except ParseError as e:
            return Grading(
                status="parse_error", raw=text, error=str(e), **common
            ), truncated
        return (
            Grading(
                status="ok",
                grade=parsed.grade,
                reasoning=parsed.reasoning or None,
                raw=text,
                **common,
            ),
            truncated,
        )


class LabelFailure(BaseModel):
    """A pair that produced no usable grade. `parse_error` is final, `api_error` is
    retried on the next run."""

    query_id: str
    doc_id: str
    labeller: str
    prompt_version: str
    prompt_sha256: str = ""
    text_sha256: str
    status: Literal["parse_error", "api_error"]
    error: str | None = None
    raw: str | None = None


def failures_path(qrels_path: Path) -> Path:
    return qrels_path.with_suffix(".failures.jsonl")


@dataclass
class LabelSummary:
    attempted: int = 0
    skipped: int = 0
    labelled: int = 0
    parse_errors: int = 0
    api_errors: int = 0
    truncated: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    failures: list[LabelFailure] = field(default_factory=list)


def pairs_to_label(
    queries: Sequence[Query],
    pool: dict[str, dict[str, list[str]]],
    docs: dict[str, DocRecord],
) -> tuple[list[tuple[Query, DocRecord]], list[tuple[str, str]]]:
    """Pooled pairs with a stored text, in query order; and the pairs lacking one."""
    pairs: list[tuple[Query, DocRecord]] = []
    missing: list[tuple[str, str]] = []
    for query in queries:
        for doc_id in pool.get(query.query_id, {}):
            if doc_id in docs:
                pairs.append((query, docs[doc_id]))
            else:
                missing.append((query.query_id, doc_id))
    return pairs, missing


def pairs_from_key(
    items: Sequence[AuditItem],
    queries: dict[str, Query],
    docs: dict[str, DocRecord],
) -> tuple[list[tuple[Query, DocRecord]], list[AuditItem]]:
    """The pairs of a sampling key, in key order, and the items that cannot be used:
    unknown query, no stored text, or a text that changed since the key was drawn (a
    label would not be about what the human saw)."""
    pairs: list[tuple[Query, DocRecord]] = []
    unusable: list[AuditItem] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        query, doc = queries.get(item.query_id), docs.get(item.doc_id)
        if query is None or doc is None or doc.text_sha256 != item.text_sha256:
            unusable.append(item)
        elif (item.query_id, item.doc_id) not in seen:
            seen.add((item.query_id, item.doc_id))
            pairs.append((query, doc))
    return pairs, unusable


def estimate_prompt_tokens(
    prompts: LabelPromptBook, pairs: Sequence[tuple[Query, DocRecord]]
) -> int:
    """Rough input size (4 characters per token), to size a run before launching it."""
    total = 0
    for query, doc in pairs:
        messages, _ = prompts.render(query, doc)
        total += sum(len(m["content"]) for m in messages) // 4
    return total


async def label_pairs(
    labeller: GradeLabeller,
    pairs: Sequence[tuple[Query, DocRecord]],
    qrels_path: Path,
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> LabelSummary:
    """Label the pairs not already stored (same labeller, document text and prompt
    hash, which covers the prompt files and the document length limit), appending
    each result as it arrives."""
    version = labeller.label_prompts.version
    prompt_sha = labeller.label_prompts.sha256
    stored = {
        q.key
        for q in load_qrels(qrels_path)
        if q.labeller == labeller.labeller and q.prompt_sha256 == prompt_sha
    }
    final_failures = {
        (f.query_id, f.doc_id, f.labeller, f.text_sha256)
        for f in read_jsonl(failures_path(qrels_path), LabelFailure)
        if f.status == "parse_error" and f.prompt_sha256 == prompt_sha
    }
    summary = LabelSummary()
    todo = []
    for query, doc in pairs:
        key = (query.query_id, doc.doc_id, labeller.labeller, doc.text_sha256)
        if key in stored or key in final_failures:
            summary.skipped += 1
        else:
            todo.append((query, doc))

    semaphore = asyncio.Semaphore(labeller.concurrency)
    lock = asyncio.Lock()
    finished = 0

    async def one(query: Query, doc: DocRecord) -> None:
        nonlocal finished
        async with semaphore:
            grading, truncated = await labeller.grade(query, doc)
        async with lock:
            summary.attempted += 1
            summary.truncated += truncated
            summary.prompt_tokens += grading.prompt_tokens or 0
            summary.completion_tokens += grading.completion_tokens or 0
            if grading.status == "ok" and grading.grade is not None:
                summary.labelled += 1
                append_jsonl(
                    qrels_path,
                    [
                        Qrel(
                            query_id=query.query_id,
                            doc_id=doc.doc_id,
                            grade=grading.grade,
                            labeller=labeller.labeller,
                            prompt_version=version,
                            prompt_sha256=prompt_sha,
                            text_sha256=doc.text_sha256,
                            rationale=grading.reasoning,
                            response_mode=grading.response_mode,
                            served_model=grading.served_model,
                            finish_reason=grading.finish_reason,
                            latency_s=grading.latency_s,
                            prompt_tokens=grading.prompt_tokens,
                            completion_tokens=grading.completion_tokens,
                            truncated=truncated,
                        )
                    ],
                )
            else:
                failure = LabelFailure(
                    query_id=query.query_id,
                    doc_id=doc.doc_id,
                    labeller=labeller.labeller,
                    prompt_version=version,
                    prompt_sha256=prompt_sha,
                    text_sha256=doc.text_sha256,
                    status="parse_error"
                    if grading.status == "parse_error"
                    else "api_error",
                    error=grading.error,
                    raw=grading.raw,
                )
                summary.failures.append(failure)
                if failure.status == "parse_error":
                    summary.parse_errors += 1
                else:
                    summary.api_errors += 1
                append_jsonl(failures_path(qrels_path), [failure])
            finished += 1
            if on_progress:
                on_progress(finished, len(todo))

    await asyncio.gather(*(one(q, d) for q, d in todo))
    return summary


def describe_run(summary: LabelSummary) -> str:
    return json.dumps(
        {
            "labelled": summary.labelled,
            "skipped": summary.skipped,
            "parse_errors": summary.parse_errors,
            "api_errors": summary.api_errors,
            "truncated": summary.truncated,
            "prompt_tokens": summary.prompt_tokens,
            "completion_tokens": summary.completion_tokens,
        }
    )


# --- probe ---------------------------------------------------------------------

PROBE_QUERY = Query(
    query_id="probe",
    text="Mon employeur peut-il refuser que je passe du congé parental total à un "
    "congé parental à temps partiel ?",
    source="probe",
    split="dev",
)
PROBE_DOC = DocRecord(
    doc_id="probe-doc",
    title="Congé parental d'éducation à temps partiel",
    source="fiches_service_public",
    text=(
        "Le salarié en congé parental d'éducation à temps plein peut demander à le "
        "transformer en congé à temps partiel (16 à 32 heures par semaine). "
        "L'employeur ne peut pas refuser. Le salarié l'informe par lettre "
        "recommandée au moins un mois avant la date de changement."
    ),
    text_sha256=text_sha256("probe"),
)


@dataclass
class LabellerProbe:
    """One real labelling call to a model, or the reason why none was made."""

    config: ModelConfig
    grading: Grading | None = None
    skipped: str | None = None

    @property
    def ok(self) -> bool:
        return self.grading is not None and self.grading.status == "ok"


async def probe_labellers(
    configs: list[ModelConfig],
    prompts: LabelPromptBook,
    client_factory: Callable[[ModelConfig], AsyncOpenAI] = make_client,
) -> list[LabellerProbe]:
    """Grade one built-in (query, document) pair with every model, through the same
    code path as `label`: key, sampling params, JSON mode, parsing. A model that
    cannot be called (key not set, id not served) is reported and does not stop the
    others. Results keep the order of `configs`."""
    clients: dict[str, AsyncOpenAI] = {}
    skipped: dict[str, LabellerProbe] = {}
    for config in configs:
        try:
            clients[config.name] = client_factory(config)
        except RuntimeError as e:  # the API key variable is not set
            skipped[config.name] = LabellerProbe(config, skipped=str(e))

    semaphores: dict[str, asyncio.Semaphore] = {}

    async def probe(config: ModelConfig, listed: bool | None) -> LabellerProbe:
        if listed is False:  # None (could not list) still deserves a call
            return LabellerProbe(config, skipped="id not served by the endpoint")
        labeller = GradeLabeller(config, prompts, client=clients[config.name])
        semaphore = semaphores.setdefault(
            labeller.concurrency_group, asyncio.Semaphore(labeller.concurrency)
        )
        async with semaphore:
            grading, _ = await labeller.grade(PROBE_QUERY, PROBE_DOC)
        return LabellerProbe(config, grading=grading)

    try:
        checks = await check_models(
            [c for c in configs if c.name in clients],
            lambda c: clients[c.name],
            close_clients=False,  # still needed for the calls below
        )
        probed = await asyncio.gather(*(probe(c.config, c.listed) for c in checks))
    finally:
        await asyncio.gather(*(client.close() for client in clients.values()))
    by_name = {p.config.name: p for p in [*skipped.values(), *probed]}
    return [by_name[c.name] for c in configs]
