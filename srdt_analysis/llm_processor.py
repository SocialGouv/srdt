import asyncio
import json
import warnings
from types import TracebackType
from typing import AsyncGenerator, Dict, Iterator, List, Optional, Type

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from srdt_analysis.albert import AlbertBase
from srdt_analysis.constants import ALBERT_ENDPOINT, LLM_MODEL, LLM_PROMPT
from srdt_analysis.logger import Logger
from srdt_analysis.models import ChunkDataListWithDocument


class LLMProcessor(AlbertBase):
    def __init__(self):
        super().__init__()
        self.logger = Logger("LLMProcessor")
        self._client = httpx.AsyncClient(timeout=30.0)
        self.rate_limit = asyncio.Semaphore(10)

    async def __aenter__(self) -> "LLMProcessor":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def __del__(self):
        if self._client is not None:
            warnings.warn(
                "LLMProcessor was not properly closed. Please use 'async with' or call 'await close()'"
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=8, max=30),
        retry=retry_if_exception_type((httpx.HTTPError, ValueError)),
    )
    async def _make_request_stream_async(
        self,
        message: str,
        system_prompt: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[str, None]:
        async with self.rate_limit:
            try:
                messages = [{"role": "system", "content": system_prompt}]
                if conversation_history:
                    messages.extend(conversation_history)
                messages.append({"role": "user", "content": message})

                async with self._client.stream(
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
                                chunk = line[6:]
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
        documents: ChunkDataListWithDocument,
        conversation_history: Optional[list] = None,
    ) -> AsyncGenerator[str, None]:
        self.logger.info("Generating streaming answer based on documents")
        document_contents = [item["content"] for item in documents["data"]]
        system_prompt = LLM_PROMPT.replace("[DOCUMENTS]", "\n".join(document_contents))
        async for token in self._make_request_stream_async(
            message, system_prompt, conversation_history
        ):
            yield token

    def get_answer_stream(
        self,
        message: str,
        documents: ChunkDataListWithDocument,
        conversation_history: Optional[list] = None,
    ) -> Iterator[str]:
        async def collect_tokens():
            tokens = []
            async with self:
                async for token in self.get_answer_stream_async(
                    message, documents, conversation_history
                ):
                    tokens.append(token)
            return tokens

        return iter(asyncio.run(collect_tokens()))
