"""Court decisions given to the answer model: port of `searchJurisprudence`
(`web/src/modules/api/prepare.ts`) and of `filterJurisprudence`
(`web/src/modules/api/jurisprudence-filter.ts`).

Search the judilibre collection, rerank, keep the top K_RERANK_JURISPRUDENCE, then
ask an LLM, one call per decision, whether it helps answer the question: only the
OUI are kept. As in the web, a call that fails twice keeps the decision and a reply
that is neither OUI nor NON drops it. Unlike the web, a failing search raises.
"""

import asyncio
import re
from typing import Any

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

from answer_eval.prompt import JUDILIBRE, Chunk, format_chunks
from judge_eval.judge import ModelConfig, describe_error
from retrieval_eval.pipeline import MAX_RERANK
from retrieval_eval.search_client import SearchAPI

TOP_K_JURISPRUDENCE = 64  # web: SEARCH_OPTIONS_JURISPRUDENCE.top_K
K_RERANK_JURISPRUDENCE = 5  # web: K_RERANK_JURISPRUDENCE

_VERDICT = re.compile(r"^\W*(OUI|NON)\b", re.IGNORECASE)


class Candidate(BaseModel):
    """A reranked decision and what the filter made of it."""

    chunk: Chunk
    kept: bool
    verdict: bool | None = None  # None: no usable reply
    raw: str | None = None
    error: str | None = None


def parse_verdict(text: str) -> bool | None:
    """Port of `parseVerdict`: True for OUI, False for NON, None otherwise."""
    match = _VERDICT.match(text.strip())
    return match.group(1).upper() == "OUI" if match else None


def filter_message(question: str, chunk: Chunk) -> str:
    return (
        f"Question : {question}\n\nArrêt :\n{format_chunks([chunk])}\n\n"
        "Répondez uniquement par OUI ou NON."
    )


async def search_jurisprudence(api: SearchAPI, text: str) -> list[Chunk]:
    """The candidates: reranked decisions, best first (search order if the rerank
    returned nothing)."""
    chunks = await api.search(
        text, top_k=TOP_K_JURISPRUDENCE, hybrid=True, collections=[JUDILIBRE]
    )
    if not chunks:
        return []
    reranked = await api.rerank(text, chunks[:MAX_RERANK])
    candidates: list[dict[str, Any]] = [
        {**r["chunk"], "rerank_score": r["rerank_score"]} for r in reranked
    ] or chunks
    return [Chunk.model_validate(c) for c in candidates[:K_RERANK_JURISPRUDENCE]]


class JurisprudenceFilter:
    def __init__(self, client: AsyncOpenAI, config: ModelConfig, instruction: str):
        if not instruction:
            raise ValueError(
                "the prompts file has no jurisprudence_filter_instruction: "
                "re-export it with scripts/web_prompts.mjs"
            )
        self.client = client
        self.config = config
        self.instruction = instruction
        self._semaphore = asyncio.Semaphore(config.concurrency)

    def describe(self) -> dict[str, Any]:
        c = self.config
        return {"name": c.name, "base_url": c.base_url, "model": c.model, **c.params}

    async def _call(self, question: str, chunk: Chunk) -> str:
        async with self._semaphore:
            completion = await self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": self.instruction},
                    {"role": "user", "content": filter_message(question, chunk)},
                ],
                **self.config.params,
            )
        if not completion.choices:
            raise ValueError("response has no choices")
        return completion.choices[0].message.content or ""

    async def judge(self, question: str, chunk: Chunk) -> Candidate:
        error = None
        for _ in range(2):  # the web retries a failed call once
            try:
                raw = await self._call(question, chunk)
            except (openai.OpenAIError, ValueError) as e:
                error = describe_error(e)
                continue
            verdict = parse_verdict(raw)
            return Candidate(chunk=chunk, kept=bool(verdict), verdict=verdict, raw=raw)
        return Candidate(chunk=chunk, kept=True, error=error)

    async def filter(self, question: str, chunks: list[Chunk]) -> list[Candidate]:
        return list(await asyncio.gather(*(self.judge(question, c) for c in chunks)))


async def jurisprudence_for(
    api: SearchAPI, decisions: JurisprudenceFilter, text: str
) -> list[Candidate]:
    return await decisions.filter(text, await search_jurisprudence(api, text))
