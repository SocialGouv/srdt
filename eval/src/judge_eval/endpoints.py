"""Client construction, the pre-flight check of configured model ids and a live probe
of each model."""

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass

import openai
from openai import AsyncOpenAI

from judge_eval.data import Criterion, Item
from judge_eval.judge import (
    ModelConfig,
    OpenAICompatibleJudge,
    Verdict,
    describe_error,
)
from judge_eval.prompts import PromptBook


def make_client(config: ModelConfig) -> AsyncOpenAI:
    api_key = os.environ.get(config.api_key_env) if config.api_key_env else None
    if config.api_key_env and not api_key:
        raise RuntimeError(
            f"Environment variable {config.api_key_env} is not set "
            f"(needed by model {config.name!r})"
        )
    return AsyncOpenAI(
        base_url=config.base_url,
        api_key=api_key or "EMPTY",
        timeout=config.timeout_s,
        # The SDK handles 429/5xx/connection errors with backoff.
        max_retries=config.max_retries,
    )


@dataclass
class ModelCheck:
    config: ModelConfig
    available: set[str] | None  # None when the endpoint could not be listed
    error: str | None = None

    @property
    def listed(self) -> bool | None:
        """Whether the configured model is served; None if it could not be checked."""
        if self.available is None:
            return None
        return self.config.model in self.available


async def list_model_ids(client: AsyncOpenAI) -> set[str]:
    """Ids served by the endpoint, including aliases (Mistral exposes e.g.
    `mistral-large-latest` as an alias of a dated id)."""
    ids: set[str] = set()
    async for model in client.models.list():
        ids.add(model.id)
        aliases = (model.model_extra or {}).get("aliases") or []
        ids.update(a for a in aliases if isinstance(a, str))
    return ids


async def check_models(
    configs: list[ModelConfig],
    client_factory: Callable[[ModelConfig], AsyncOpenAI] = make_client,
    close_clients: bool = True,
) -> list[ModelCheck]:
    """List the models of each endpoint (once per endpoint) and check the configured
    ids against them. The clients are closed here, inside the running event loop
    (left open, they fail noisily when garbage-collected after it ended), unless the
    caller owns them (`close_clients=False`)."""
    # Several models usually share an endpoint: list each one only once.
    listings: dict[tuple[str, str | None], tuple[set[str] | None, str | None]] = {}
    checks = []
    for config in configs:
        endpoint = (config.base_url, config.api_key_env)
        if endpoint not in listings:
            client = client_factory(config)
            try:
                listings[endpoint] = (await list_model_ids(client), None)
            except openai.OpenAIError as e:
                listings[endpoint] = (None, describe_error(e))
            finally:
                if close_clients:
                    await client.close()
        available, error = listings[endpoint]
        checks.append(ModelCheck(config, available, error))
    return checks


@dataclass
class ModelProbe:
    """One real judging call to a model, or the reason why none was made."""

    config: ModelConfig
    verdict: Verdict | None = None
    skipped: str | None = None

    @property
    def ok(self) -> bool:
        return self.verdict is not None and self.verdict.status == "ok"


async def probe_models(
    configs: list[ModelConfig],
    item: Item,
    criterion: Criterion,
    prompts: PromptBook,
    client_factory: Callable[[ModelConfig], AsyncOpenAI] = make_client,
) -> list[ModelProbe]:
    """Judge one item with every model, through the same code path as `run`.

    Unlike `check_models`, this exercises the key, the sampling params, the response
    format and the parsing. A model that cannot be called (key not set, id not
    served) is reported and does not stop the others. Results keep the order of
    `configs`.
    """
    clients: dict[str, AsyncOpenAI] = {}
    skipped: dict[str, ModelProbe] = {}
    for config in configs:
        try:
            clients[config.name] = client_factory(config)
        except RuntimeError as e:  # the API key variable is not set
            skipped[config.name] = ModelProbe(config, skipped=str(e))

    semaphores: dict[str, asyncio.Semaphore] = {}

    async def probe(check: ModelCheck) -> ModelProbe:
        config = check.config
        if check.listed is False:  # None (could not list) still deserves a call
            return ModelProbe(config, skipped="id not served by the endpoint")
        judge = OpenAICompatibleJudge(config, prompts, client=clients[config.name])
        semaphore = semaphores.setdefault(
            judge.concurrency_group, asyncio.Semaphore(judge.concurrency)
        )
        async with semaphore:
            return ModelProbe(config, verdict=await judge.judge(item, criterion))

    try:
        checks = await check_models(
            [c for c in configs if c.name in clients],
            lambda c: clients[c.name],
            close_clients=False,  # still needed for the calls below
        )
        probed = await asyncio.gather(*(probe(c) for c in checks))
    finally:
        await asyncio.gather(*(client.close() for client in clients.values()))
    by_name = {p.config.name: p for p in [*skipped.values(), *probed]}
    return [by_name[c.name] for c in configs]
