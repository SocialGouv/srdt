"""Judges: the interface, the verdict parser and the OpenAI-compatible LLM judge."""

import json
import re
import time
import tomllib
import unicodedata
from pathlib import Path
from typing import Any, Literal, Protocol

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, field_validator

from judge_eval.data import Criterion, Item
from judge_eval.prompts import PromptBook

Status = Literal["ok", "parse_error", "api_error"]


class Verdict(BaseModel):
    """Outcome of one judgement.

    `parse_error` (the model answered but not in a usable form) is a real result
    and is counted; `api_error` (no answer obtained) is retried on resume.
    """

    status: Status
    label: bool | None = None  # True = "Oui"
    reasoning: str | None = None
    raw: str | None = None
    error: str | None = None
    response_mode: str | None = None
    # Model id reported by the server; differs from the configured id for aliases.
    served_model: str | None = None
    finish_reason: str | None = None
    latency_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Judge(Protocol):
    name: str
    criteria: tuple[Criterion, ...]
    # Judges of the same group share one pool of `concurrency` parallel calls
    # (rate limits apply per provider key, not per model).
    concurrency_group: str
    concurrency: int

    def describe(self) -> dict[str, Any]:
        """Settings stored in the run config; must be stable across invocations."""
        ...

    async def judge(self, item: Item, criterion: Criterion) -> Verdict: ...


# --- Parsing -------------------------------------------------------------


class ParseError(ValueError):
    pass


def _to_label(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore")
    word = ascii_text.decode().strip(" \t\n.!\"'").lower()
    if word in {"oui", "yes", "true"}:
        return True
    if word in {"non", "no", "false"}:
        return False
    return None


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reasoning: str = ""
    verdict: bool

    @field_validator("verdict", mode="before")
    @classmethod
    def _normalise_verdict(cls, value: Any) -> bool:
        label = _to_label(value)
        if label is None:
            raise ValueError(f"unrecognised verdict {value!r}")
        return label


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_VERDICT_FIELD = re.compile(r'"verdict"\s*:\s*"([^"]*)"', re.IGNORECASE)


def _json_objects(text: str):
    """Yield every JSON object that can be decoded starting at a '{'."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value


def parse_verdict(text: str) -> JudgeOutput:
    """Extract {"reasoning", "verdict"} from a model reply, tolerating prose,
    code fences, <think> blocks and truncated JSON. Raises ParseError otherwise.
    A verdict is never guessed from free text."""
    cleaned = _THINK_BLOCK.sub("", text).strip()
    fenced = _CODE_FENCE.search(cleaned)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(cleaned)

    rejected: str | None = None
    for candidate in candidates:
        for obj in _json_objects(candidate):
            if "verdict" not in obj:
                continue
            try:
                return JudgeOutput.model_validate(obj)
            except ValueError as e:
                rejected = str(e)

    # Truncated JSON (e.g. cut by max_tokens after the verdict field).
    field = _VERDICT_FIELD.search(cleaned)
    if field and (label := _to_label(field.group(1))) is not None:
        return JudgeOutput(verdict=label)
    raise ParseError(rejected or "no JSON object with a 'verdict' field found")


# --- LLM judge -----------------------------------------------------------

RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
                "verdict": {"type": "string", "enum": ["Oui", "Non"]},
            },
            "required": ["reasoning", "verdict"],
            "additionalProperties": False,
        },
    },
}

# Strongest to weakest way of asking for JSON. "prompt" relies on the
# instructions in the system prompt alone.
FALLBACK_CHAIN = ("json_schema", "json_object", "prompt")


DEFAULT_PARAMS: dict[str, Any] = {"temperature": 0}


class ProviderConfig(BaseModel):
    """One `[providers.<name>]` table: an endpoint, its key and defaults."""

    model_config = ConfigDict(extra="forbid")

    # Must include the version path, e.g. https://api.mistral.ai/v1
    base_url: str
    # Name of the environment variable holding the key; omit for local servers.
    api_key_env: str | None = None
    # Parallel calls allowed for the whole provider, shared by all its models.
    concurrency: int = Field(default=4, ge=1)
    response_format: Literal["auto", "json_schema", "json_object", "prompt"] = "auto"
    # Sent verbatim to chat.completions.create. When the table is absent the
    # default is {"temperature": 0}; an empty table sends nothing (needed for
    # models that reject temperature).
    params: dict[str, Any] = Field(default_factory=lambda: dict(DEFAULT_PARAMS))
    timeout_s: float = 120
    max_retries: int = 5


class ModelEntry(BaseModel):
    """One `[[models]]` entry: a model of a provider, with optional overrides."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    name: str | None = None  # label in reports; defaults to "<provider>/<model>"
    response_format: Literal["auto", "json_schema", "json_object", "prompt"] | None = (
        None
    )
    params: dict[str, Any] | None = None
    timeout_s: float | None = None
    max_retries: int | None = None


class ModelConfig(BaseModel):
    """A model with its provider settings resolved."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    base_url: str
    model: str
    provider: str = ""
    api_key_env: str | None = None
    concurrency: int = Field(default=4, ge=1)
    response_format: Literal["auto", "json_schema", "json_object", "prompt"] = "auto"
    params: dict[str, Any] = Field(default_factory=lambda: dict(DEFAULT_PARAMS))
    timeout_s: float = 120
    max_retries: int = 5

    @field_validator("name")
    @classmethod
    def _not_reserved(cls, value: str) -> str:
        if value.startswith("baseline:"):
            raise ValueError("names starting with 'baseline:' are reserved")
        return value


def load_models(path: Path) -> list[ModelConfig]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    providers = {
        name: ProviderConfig.model_validate(table)
        for name, table in data.get("providers", {}).items()
    }
    configs: list[ModelConfig] = []
    for index, raw in enumerate(data.get("models", [])):
        try:
            entry = ModelEntry.model_validate(raw)
        except ValueError as e:
            raise ValueError(f"{path}: [[models]] entry {index + 1}:\n{e}") from e
        provider = providers.get(entry.provider)
        if provider is None:
            raise ValueError(
                f"{path}: model {entry.model!r} uses unknown provider "
                f"{entry.provider!r}; defined providers: {sorted(providers)}"
            )
        overrides = entry.model_dump(
            include={"response_format", "params", "timeout_s", "max_retries"},
            exclude_none=True,
        )
        configs.append(
            ModelConfig.model_validate(
                {
                    **provider.model_dump(),
                    **overrides,
                    "name": entry.name or f"{entry.provider}/{entry.model}",
                    "provider": entry.provider,
                    "model": entry.model,
                }
            )
        )
    names = [c.name for c in configs]
    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(f"{path}: model names must be unique, duplicated: {dupes}")
    return configs


def _format_exception(error: BaseException) -> str:
    message = str(error)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def describe_error(error: BaseException) -> str:
    """The error, plus the exception behind it when there is one.

    The OpenAI client reports every network failure as a bare "Connection error.";
    the real reason (DNS failure, connection refused or reset, TLS, server hung
    up...) is the exception it was raised from. HTTP status errors are raised with
    their context suppressed, and stay as they are.
    """
    root, seen = error, {id(error)}
    while True:
        cause = root.__cause__
        if cause is None and not root.__suppress_context__:
            cause = root.__context__
        if cause is None or id(cause) in seen:
            break
        root = cause
        seen.add(id(root))
    text = _format_exception(error)
    if root is not error:
        text += f" (cause: {_format_exception(root)})"
    return text


class OpenAICompatibleJudge:
    """Judge backed by any /v1/chat/completions endpoint (Albert, Mistral,
    OpenAI, Ollama, vLLM...)."""

    criteria = tuple(Criterion)
    # Subclasses asking for another JSON shape (e.g. retrieval_eval's graded
    # labeller) replace this; the fallback chain then applies to their schema.
    response_schema: dict[str, Any] = RESPONSE_SCHEMA

    def __init__(
        self,
        config: ModelConfig,
        prompts: PromptBook,
        client: AsyncOpenAI | None = None,
    ):
        self.name = config.name
        self.concurrency = config.concurrency
        self.concurrency_group = config.provider or config.name
        self.config = config
        self.prompts = prompts
        if client is None:
            from judge_eval.endpoints import make_client  # avoids an import cycle

            client = make_client(config)
        self.client = client
        self._modes = (
            FALLBACK_CHAIN
            if config.response_format == "auto"
            else (config.response_format,)
        )
        self._mode_index = 0

    def describe(self) -> dict[str, Any]:
        c = self.config
        return {
            "kind": "openai-compatible",
            "base_url": c.base_url,
            "model": c.model,
            "response_format": c.response_format,
            "params": c.params,
        }

    async def judge(self, item: Item, criterion: Criterion) -> Verdict:
        messages = self.prompts.render(item, criterion)
        started = time.perf_counter()
        try:
            completion, mode = await self._complete(messages)
        except openai.OpenAIError as e:
            return Verdict(
                status="api_error",
                error=describe_error(e),
                latency_s=time.perf_counter() - started,
            )
        latency = time.perf_counter() - started

        usage = completion.usage
        common = {
            "response_mode": mode,
            "served_model": completion.model,
            "latency_s": latency,
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
        }
        if not completion.choices:
            return Verdict(
                status="api_error", error="response has no choices", **common
            )
        choice = completion.choices[0]
        text = choice.message.content or ""
        common["finish_reason"] = choice.finish_reason
        try:
            parsed = parse_verdict(text)
        except ParseError as e:
            return Verdict(status="parse_error", raw=text, error=str(e), **common)
        return Verdict(
            status="ok",
            label=parsed.verdict,
            reasoning=parsed.reasoning or None,
            raw=text,
            **common,
        )

    async def _complete(self, messages: list[dict[str, str]]):
        """Call the API, stepping down the fallback chain on HTTP 400/422.

        The step-down is only kept (for all later calls) if a weaker mode then
        succeeds: that shows the mode was the problem and not, say, an oversized
        prompt. If every mode fails, the first error is raised.
        """
        start = self._mode_index
        first_error: openai.APIStatusError | None = None
        for index in range(start, len(self._modes)):
            mode = self._modes[index]
            kwargs: dict[str, Any] = {
                "model": self.config.model,
                "messages": messages,
                **self.config.params,
            }
            if mode == "json_schema":
                kwargs["response_format"] = self.response_schema
            elif mode == "json_object":
                kwargs["response_format"] = {"type": "json_object"}
            try:
                completion = await self.client.chat.completions.create(**kwargs)
            except (openai.BadRequestError, openai.UnprocessableEntityError) as e:
                first_error = first_error or e
                continue
            if index > start:
                self._mode_index = max(self._mode_index, index)
            return completion, mode
        assert first_error is not None
        raise first_error
