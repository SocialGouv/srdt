import asyncio
import json
from typing import AsyncGenerator, Iterator

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from srdt_analysis.albert import AlbertBase
from srdt_analysis.constants import ALBERT_ENDPOINT, LLM_ANSWER_PROMPT, LLM_MODEL
from srdt_analysis.logger import Logger
from srdt_analysis.models import RAGChunkSearchResultEnriched


class LLMProcessor(AlbertBase):
    def __init__(self):
        super().__init__()
        self.logger = Logger("LLMProcessor")
        self.client = httpx.AsyncClient(timeout=30.0)
        self.rate_limit = asyncio.Semaphore(10)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, ValueError)),
    )
    async def _make_request_stream_async(
        self,
        message: str,
        system_prompt: str,
    ) -> AsyncGenerator[str, None]:
        async with self.rate_limit:
            try:
                messages = [{"role": "system", "content": system_prompt}]
                messages.append({"role": "user", "content": message})

                async with self.client.stream(
                    "POST",
                    f"{ALBERT_ENDPOINT}/v1/chat/completions",
                    headers=self.headers,
                    json={
                        "messages": messages,
                        "model": LLM_MODEL,
                        "stream": True,
                    },
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: ") and line.strip() != "data: [DONE]":
                            try:
                                chunk = line[len("data: ") :]
                                chunk_data = json.loads(chunk)
                                if (
                                    content := chunk_data["choices"][0]
                                    .get("delta", {})
                                    .get("content")
                                ):
                                    yield content
                            except json.JSONDecodeError as e:
                                self.logger.error(f"Failed to parse chunk: {e}")
                                continue

            except httpx.HTTPStatusError as e:
                self.logger.error(
                    f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
                )
                raise
            except httpx.RequestError as e:
                self.logger.error(f"Request error occurred: {str(e)}")
                raise
            except Exception as e:
                self.logger.error(f"Unexpected error: {str(e)}")
                raise

    async def get_answer_stream_async(
        self,
        message: str,
        documents: RAGChunkSearchResultEnriched,
    ) -> AsyncGenerator[str, None]:
        self.logger.info("Generating streaming answer based on documents")
        document_contents = [item["content"] for item in documents["data"]]
        system_prompt = f"{LLM_ANSWER_PROMPT}\n Mes documents sont :\n{'\n'.join(document_contents)}\n"
        async for token in self._make_request_stream_async(message, system_prompt):
            yield token

    def get_answer_stream(
        self,
        message: str,
        documents: RAGChunkSearchResultEnriched,
    ) -> Iterator[str]:
        async def collect_tokens():
            tokens = []
            async for token in self.get_answer_stream_async(
                message,
                documents,
            ):
                tokens.append(token)
            return tokens

        return iter(asyncio.run(collect_tokens()))
