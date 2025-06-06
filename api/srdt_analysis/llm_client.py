import asyncio
import json
from typing import AsyncIterator, Sequence, Union

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from srdt_analysis.logger import Logger
from srdt_analysis.models import (
    LLMChatPayload,
    SystemLLMMessage,
    UserLLMMessage,
)


class LLMClient:
    def __init__(self, base_url, api_key, model):
        super().__init__()
        self.logger = Logger("LLMCLient")
        self.client = httpx.AsyncClient(timeout=30.0)
        self.rate_limit = asyncio.Semaphore(10)
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
        }
        self.model = model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, ValueError)),
    )
    async def _make_chat_completions_async(
        self,
        system_prompt: str,
        chat_history: list[UserLLMMessage],
    ) -> str:
        async with self.rate_limit:
            try:
                messages: Sequence[Union[SystemLLMMessage, UserLLMMessage]] = [
                    SystemLLMMessage(role="system", content=system_prompt),
                ] + chat_history

                payload: LLMChatPayload = {
                    "messages": messages,
                    "model": self.model,
                }

                # self.logger.debug(payload)

                response = await self.client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=self.headers,
                    json=payload,
                )
                response.raise_for_status()

                response_json = response.json()
                # self.logger.debug(response_json)

                return response_json["choices"][0]["message"]["content"]

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

    async def _make_chat_completions_stream_async(
        self,
        system_prompt: str,
        chat_history: list[UserLLMMessage],
    ) -> AsyncIterator[str]:
        async with self.rate_limit:
            try:
                messages: Sequence[Union[SystemLLMMessage, UserLLMMessage]] = [
                    SystemLLMMessage(role="system", content=system_prompt),
                ] + chat_history

                payload: LLMChatPayload = {
                    "messages": messages,
                    "model": self.model,
                    "stream": True,
                }

                async with self.client.stream(
                    "POST",
                    f"{self.base_url}/v1/chat/completions",
                    headers=self.headers,
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line.strip():
                            if line.startswith("data: "):
                                data = line[6:]  # Remove "data: " prefix
                                if data.strip() == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data)
                                    if (
                                        "choices" in chunk
                                        and len(chunk["choices"]) > 0
                                        and "delta" in chunk["choices"][0]
                                        and "content" in chunk["choices"][0]["delta"]
                                    ):
                                        content = chunk["choices"][0]["delta"][
                                            "content"
                                        ]
                                        if content:
                                            yield content
                                except json.JSONDecodeError:
                                    # Skip invalid JSON lines
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

    async def generate_completions_async(
        self,
        system_prompt: str,
        chat_history: list[UserLLMMessage],
    ) -> str:
        self.logger.info("Generating a chat completions answer")
        return await self._make_chat_completions_async(system_prompt, chat_history)

    async def generate_completions_stream_async(
        self,
        system_prompt: str,
        chat_history: list[UserLLMMessage],
    ) -> AsyncIterator[str]:
        self.logger.info("Generating a streaming chat completions answer")
        async for chunk in self._make_chat_completions_stream_async(
            system_prompt, chat_history
        ):
            yield chunk
