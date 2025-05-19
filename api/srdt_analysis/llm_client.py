import asyncio
from typing import Sequence, Union

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

                self.logger.debug(payload)

                response = await self.client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=self.headers,
                    json=payload,
                )
                response.raise_for_status()

                response_json = response.json()
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

    async def generate_completions_async(
        self,
        system_prompt: str,
        chat_history: list[UserLLMMessage],
    ) -> str:
        self.logger.info("Generating a chat completions answer")
        return await self._make_chat_completions_async(system_prompt, chat_history)
