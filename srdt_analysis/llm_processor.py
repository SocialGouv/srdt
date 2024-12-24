import asyncio
import json
from typing import AsyncGenerator, Sequence, Union

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from srdt_analysis.albert import AlbertBase
from srdt_analysis.constants import ALBERT_ENDPOINT, LLM_MODEL
from srdt_analysis.logger import Logger
from srdt_analysis.models import (
    LLMChatPayload,
    LLMMessage,
    LLMMessageSecurized,
    RAGChunkSearchResultEnriched,
)


class LLMProcessor(AlbertBase):
    def __init__(self):
        super().__init__()
        self.logger = Logger("LLMProcessor")
        self.client = httpx.AsyncClient(timeout=30.0)
        self.rate_limit = asyncio.Semaphore(10)

    async def _stream_response(
        self, payload: LLMChatPayload
    ) -> AsyncGenerator[str, None]:
        async with self.rate_limit:
            try:
                async with self.client.stream(
                    "POST",
                    f"{ALBERT_ENDPOINT}/v1/chat/completions",
                    headers=self.headers,
                    json=payload,
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, ValueError)),
    )
    async def _make_chat_completions_stream_async(
        self,
        chat_history: list[LLMMessageSecurized],
        system_prompt: str,
    ) -> AsyncGenerator[str, None]:
        messages: Sequence[Union[LLMMessage, LLMMessageSecurized]] = [
            LLMMessage(role="system", content=system_prompt),
        ] + chat_history
        payload: LLMChatPayload = {
            "messages": messages,
            "model": LLM_MODEL,
            "stream": True,
        }
        async for content in self._stream_response(payload):
            yield content

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, ValueError)),
    )
    async def _make_chat_completions_async(self, prompt: str, user_message: str) -> str:
        async with self.rate_limit:
            try:
                messages: list[LLMMessage] = [
                    LLMMessage(role="system", content=prompt),
                    LLMMessage(role="user", content=user_message),
                ]

                payload: LLMChatPayload = {
                    "messages": messages,
                    "model": LLM_MODEL,
                    "stream": False,
                }

                response = await self.client.post(
                    f"{ALBERT_ENDPOINT}/v1/chat/completions",
                    headers=self.headers,
                    json=payload,
                )
                response.raise_for_status()

                response_data = response.json()
                return response_data["choices"][0]["message"]["content"]

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

    async def get_chat_completions_stream_async(
        self,
        chat_history: list[LLMMessageSecurized],
        prompt: str,
        documents: RAGChunkSearchResultEnriched,
    ) -> AsyncGenerator[str, None]:
        self.logger.info("Generating a chat completions answer based on documents")
        document_contents = [item["content"] for item in documents["data"]]
        system_prompt = (
            f"{prompt}\n Mes documents sont :\n{'\n'.join(document_contents)}\n"
        )
        async for token in self._make_chat_completions_stream_async(
            chat_history, system_prompt
        ):
            yield token

    async def get_completions_async(
        self,
        prompt: str,
        user_message: str,
    ) -> str:
        self.logger.info("Generating a chat completions answer")
        return await self._make_chat_completions_async(prompt, user_message)
