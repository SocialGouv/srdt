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

    @property
    def key(self) -> tuple[str, str]:
        return (self.generator, self.query_id)

    @property
    def item_id(self) -> str:
        return f"{self.generator}::{self.query_id}"


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


def render(prompts: WebPrompts, context: Context) -> list[dict[str, Any]]:
    system = system_prompt(
        prompts,
        idcc=context.idcc,
        idcc_name=context.idcc_name,
        fiches=context.fiches,
        code=context.code,
        idcc_chunks=context.idcc_chunks,
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


async def generate_one(
    client: AsyncOpenAI,
    config: ModelConfig,
    query_id: str,
    chat: list[dict[str, Any]],
) -> Answer:
    common: dict[str, Any] = {
        "generator": config.name,
        "query_id": query_id,
        "prompt_sha256": sha256_text(json.dumps(chat, ensure_ascii=False)),
    }
    started = time.perf_counter()
    try:
        completion = await client.chat.completions.create(
            model=config.model, messages=chat, **config.params
        )
    except openai.OpenAIError as e:
        return Answer(
            status="api_error",
            error=describe_error(e),
            latency_s=time.perf_counter() - started,
            **common,
        )
    usage = completion.usage
    common |= {
        "served_model": completion.model,
        "latency_s": time.perf_counter() - started,
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
    }
    if not completion.choices:
        return Answer(status="api_error", error="response has no choices", **common)
    choice = completion.choices[0]
    text = (choice.message.content or "").strip()
    return Answer(
        status="ok" if text else "empty",
        answer=text or None,
        finish_reason=choice.finish_reason,
        **common,
    )


async def run_generation(
    generators: Sequence[ModelConfig],
    contexts: Sequence[Context],
    prompts: WebPrompts,
    run_dir: Path,
    client_factory=make_client,
) -> RunSummary:
    answers_path = run_dir / ANSWERS_FILE
    repair_trailing_partial_line(answers_path)
    final = {a.key for a in load_answers(answers_path) if a.status != "api_error"}

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
