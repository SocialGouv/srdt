"""Answers of each model to each question, from the same prompts.

runs/<run_id>/
    contexts.jsonl   the frozen knowledge base of each question (`contexts`)
    config.json      hashes of the contexts and templates, settings of each model
    answers.jsonl    one line per (generator, question), append-only

Resumable like judge_eval's runner: re-running skips what is stored, and only
`api_error` results are retried.
"""

import asyncio
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

from answer_eval.contexts import Context
from answer_eval.prompt import WebPrompts, messages, sha256_text, system_prompt
from judge_eval.endpoints import make_client
from judge_eval.judge import ModelConfig, describe_error
from retrieval_eval.jsonl import read_jsonl, repair_trailing_partial_line

CONTEXTS_FILE = "contexts.jsonl"
CONFIG_FILE = "config.json"
ANSWERS_FILE = "answers.jsonl"

# `empty`: the model answered nothing (e.g. a reasoning model cut off by its token
# limit). It is a result, not retried.
Status = Literal["ok", "empty", "api_error"]

VARIANT_SEP = "+"


class Answer(BaseModel):
    generator: str
    query_id: str
    status: Status
    answer: str | None = None
    error: str | None = None
    prompt_sha256: str
    served_model: str | None = None
    finish_reason: str | None = None
    latency_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # Received as a stream (`generate --stream`): same answer, but the connection
    # stays active, which some gateways need for long generations.
    streamed: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return (self.generator, self.query_id)

    @property
    def item_id(self) -> str:
        return f"{self.generator}::{self.query_id}"

    @property
    def base(self) -> str:
        """The model this answer counts for: `glm+32k` (a variant generated with
        another setting to replace one answer) counts for `glm`."""
        return self.generator.split(VARIANT_SEP, 1)[0]


class RunConfigError(RuntimeError):
    pass


@dataclass
class RunSummary:
    attempted: int = 0
    skipped: int = 0
    ok: int = 0
    empty: int = 0
    api_errors: int = 0


def load_contexts(run_dir: Path) -> list[Context]:
    return list(read_jsonl(run_dir / CONTEXTS_FILE, Context))


def load_answers(path: Path) -> list[Answer]:
    """Latest record per (generator, question)."""
    latest: dict[tuple[str, str], Answer] = {}
    for answer in read_jsonl(path, Answer):
        latest.pop(answer.key, None)
        latest[answer.key] = answer
    return list(latest.values())


def effective_answers(answers: list[Answer]) -> list[Answer]:
    """One answer per (model, question): a successful variant answer
    (`<model>+<setting>`) replaces the model's own answer; a failed variant replaces
    nothing. Independent of the order of `answers`."""
    groups: dict[tuple[str, str], list[Answer]] = {}
    for answer in answers:
        groups.setdefault((answer.base, answer.query_id), []).append(answer)
    chosen = []
    for group in groups.values():
        variants = [a for a in group if a.generator != a.base and a.status == "ok"]
        own = [a for a in group if a.generator == a.base]
        chosen.append((variants or own or group)[-1])
    return chosen


def render(prompts: WebPrompts, context: Context) -> list[dict[str, Any]]:
    system = system_prompt(
        prompts,
        idcc=context.idcc,
        idcc_name=context.idcc_name,
        fiches=context.fiches,
        code=context.code,
        idcc_chunks=context.idcc_chunks,
        jurisprudence=context.jurisprudence,
    )
    return messages(system, context.text)


def describe(config: ModelConfig) -> dict[str, Any]:
    return {"base_url": config.base_url, "model": config.model, "params": config.params}


def check_run_config(
    run_dir: Path, prompts: WebPrompts, generators: Sequence[ModelConfig]
) -> None:
    """Create or update config.json; refuse to mix results from different setups."""
    path = run_dir / CONFIG_FILE
    contexts_sha = sha256_text((run_dir / CONTEXTS_FILE).read_text(encoding="utf-8"))
    setup = {
        "contexts_sha256": contexts_sha,
        "prompts_config": prompts.config,
        "prompts_sha256": prompts.sha256,
    }
    config: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **setup,
        "generators": {},
    }
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        for field, value in setup.items():
            if existing.get(field) != value:
                raise RunConfigError(
                    f"{path}: {field} differs from this run's setup "
                    f"({existing.get(field)!r} vs {value!r}). "
                    "Use a new --run-id instead of mixing results."
                )
        config = existing
    for generator in generators:
        settings = describe(generator)
        previous = config["generators"].get(generator.name)
        if previous is not None and previous != settings:
            raise RunConfigError(
                f"{path}: settings of {generator.name!r} changed since the run "
                "started. Use a new --run-id or another model name."
            )
        config["generators"][generator.name] = settings
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def _text(content: Any) -> str | None:
    """The answer in a message `content`: a string, or, from the Mistral API with
    `reasoning_effort`, a list of parts where `thinking` holds the hidden reasoning
    and `text` the answer. Only the `text` parts are kept."""
    if content is None or isinstance(content, str):
        return content
    parts = []
    for part in content:
        part = part if isinstance(part, dict) else part.model_dump()
        if part.get("type") == "text":
            parts.append(part.get("text") or "")
    return "".join(parts)


async def _complete(
    client: AsyncOpenAI, config: ModelConfig, chat: list[dict[str, Any]]
) -> dict[str, Any]:
    completion = await client.chat.completions.create(
        model=config.model, messages=chat, **config.params
    )
    usage = completion.usage
    out: dict[str, Any] = {
        "served_model": completion.model,
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
    }
    if completion.choices:
        choice = completion.choices[0]
        out |= {
            "text": _text(choice.message.content),
            "finish_reason": choice.finish_reason,
        }
    return out


async def _stream(
    client: AsyncOpenAI, config: ModelConfig, chat: list[dict[str, Any]]
) -> dict[str, Any]:
    stream = await client.chat.completions.create(
        model=config.model,
        messages=chat,
        stream=True,
        stream_options={"include_usage": True},
        **config.params,
    )
    parts: list[str] = []
    out: dict[str, Any] = {}
    got_choice = False
    async for chunk in stream:
        out["served_model"] = chunk.model or out.get("served_model")
        if chunk.usage:
            out["prompt_tokens"] = chunk.usage.prompt_tokens
            out["completion_tokens"] = chunk.usage.completion_tokens
        for choice in chunk.choices:
            got_choice = True
            if choice.delta and choice.delta.content:
                parts.append(_text(choice.delta.content))
            if choice.finish_reason:
                out["finish_reason"] = choice.finish_reason
    if got_choice:
        out["text"] = "".join(parts)
    return out


async def generate_one(
    client: AsyncOpenAI,
    config: ModelConfig,
    query_id: str,
    chat: list[dict[str, Any]],
    stream: bool = False,
) -> Answer:
    common: dict[str, Any] = {
        "generator": config.name,
        "query_id": query_id,
        "prompt_sha256": sha256_text(json.dumps(chat, ensure_ascii=False)),
        "streamed": stream,
    }
    started = time.perf_counter()
    try:
        result = await (_stream if stream else _complete)(client, config, chat)
    except (openai.OpenAIError, httpx.HTTPError) as e:
        # httpx errors can surface while a stream is being read.
        return Answer(
            status="api_error",
            error=describe_error(e),
            latency_s=time.perf_counter() - started,
            **common,
        )
    text = result.pop("text", None)
    common |= result | {"latency_s": time.perf_counter() - started}
    if text is None:
        return Answer(status="api_error", error="response has no choices", **common)
    text = text.strip()
    return Answer(status="ok" if text else "empty", answer=text or None, **common)


async def run_generation(
    generators: Sequence[ModelConfig],
    contexts: Sequence[Context],
    prompts: WebPrompts,
    run_dir: Path,
    client_factory=make_client,
    stream: bool = False,
    redo: Sequence[str] = (),
) -> RunSummary:
    """`redo`: item ids (`<generator>::<query_id>`) generated again even if stored,
    e.g. an answer cut by a provider's output limit. The new record supersedes the
    old one, which stays in the file."""
    answers_path = run_dir / ANSWERS_FILE
    repair_trailing_partial_line(answers_path)
    known = {f"{g.name}::{c.query_id}" for g in generators for c in contexts}
    if unknown := set(redo) - known:
        raise ValueError(f"--redo: unknown answer(s) {sorted(unknown)}")
    final = {
        a.key
        for a in load_answers(answers_path)
        if a.status != "api_error" and a.item_id not in redo
    }

    summary = RunSummary()
    pending: list[tuple[ModelConfig, Context]] = []
    for generator in generators:
        for context in contexts:
            if (generator.name, context.query_id) in final:
                summary.skipped += 1
            else:
                pending.append((generator, context))

    clients = {g.name: client_factory(g) for g in generators}
    semaphores: dict[str, asyncio.Semaphore] = {}
    for g in generators:
        semaphores.setdefault(g.provider or g.name, asyncio.Semaphore(g.concurrency))
    write_lock = asyncio.Lock()
    total = len(pending)

    async def work(generator: ModelConfig, context: Context, out) -> None:
        async with semaphores[generator.provider or generator.name]:
            answer = await generate_one(
                clients[generator.name],
                generator,
                context.query_id,
                render(prompts, context),
                stream,
            )
        async with write_lock:
            out.write(answer.model_dump_json() + "\n")
            out.flush()
            summary.attempted += 1
            if answer.status == "ok":
                summary.ok += 1
            elif answer.status == "empty":
                summary.empty += 1
            else:
                summary.api_errors += 1
                print(
                    f"  {generator.name} / {context.query_id}: {answer.error}",
                    file=sys.stderr,
                )
            print(
                f"  {summary.attempted}/{total} done "
                f"({generator.name}, {context.query_id}, {answer.status}, "
                f"{answer.latency_s or 0:.0f}s)",
                file=sys.stderr,
            )

    try:
        with answers_path.open("a", encoding="utf-8") as out:
            await asyncio.gather(*(work(g, c, out) for g, c in pending))
    finally:
        await asyncio.gather(*(c.close() for c in clients.values()))
    return summary
