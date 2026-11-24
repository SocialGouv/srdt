import asyncio
import json
from typing import AsyncIterator, NoReturn, Sequence, Union

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from srdt_analysis.core.constants import (
    API_TIMEOUT,
    MISTRAL_API_HOST,
    MISTRAL_TEMPERATURE,
)
from srdt_analysis.core.exceptions import (
    ExternalServiceError,
    ServiceUnavailableError,
)
from srdt_analysis.core.logger import Logger
from srdt_analysis.core.models import (
    LLMChatPayload,
    SystemLLMMessage,
    UserLLMMessage,
)


def extract_text(content: object) -> str:
    """The answer text of a message (or stream delta) `content`.

    It is a string for most models. Reasoning models (Mistral with `reasoning_effort`)
    return a list of blocks instead, `[{"type": "thinking", ...}, {"type": "text",
    "text": "..."}]`: only the text blocks are the answer, the thinking ones are
    dropped. Null gives an empty string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else block.get("text") or ""
            for block in content
            if isinstance(block, str)
            or (isinstance(block, dict) and block.get("type") == "text")
        )
    return ""


class LLMClient:
    def __init__(self, base_url, api_key, model):
        super().__init__()
        self.logger = Logger("LLMClient")
        self.client = httpx.AsyncClient(timeout=API_TIMEOUT)
        self.rate_limit = asyncio.Semaphore(10)
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
        }
        self.model = model
        # Température forcée pour les modèles Mistral (appelés via l'API Mistral ou
        # servis par un autre fournisseur, ex. Albert), laissée au défaut du
        # fournisseur pour les autres.
        is_mistral = MISTRAL_API_HOST in (base_url or "") or (model or "").startswith(
            "mistral"
        )
        self.temperature: float | None = MISTRAL_TEMPERATURE if is_mistral else None

    def _base_payload(
        self,
        messages: Sequence[Union[SystemLLMMessage, UserLLMMessage]],
    ) -> LLMChatPayload:
        payload: LLMChatPayload = {
            "messages": messages,
            "model": self.model,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        return payload

    def _raise_for_status(self, e: httpx.HTTPStatusError) -> NoReturn:
        self.logger.error(
            f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
        )
        status = e.response.status_code
        if status == 401:
            raise ExternalServiceError(
                "LLM API key rejected (HTTP 401)", service="LLM"
            ) from e
        elif status in (404, 422):
            raise ExternalServiceError(
                f"LLM model '{self.model}' not found or unprocessable (HTTP {status})",
                service="LLM",
            ) from e
        elif status == 429:
            raise ExternalServiceError(
                "LLM rate limit exceeded (HTTP 429)", service="LLM"
            ) from e
        else:
            raise ExternalServiceError(
                f"LLM service error (HTTP {status})", service="LLM"
            ) from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(
            (httpx.HTTPError, ValueError, ExternalServiceError)
        ),
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

                payload = self._base_payload(messages)

                # self.logger.debug(payload)

                response = await self.client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=self.headers,
                    json=payload,
                )
                response.raise_for_status()

                response_json = response.json()
                # self.logger.debug(response_json)

                choice = response_json["choices"][0]
                text = extract_text(choice["message"].get("content"))
                if not text:
                    # raised inside the retry: a null or thinking-only answer is
                    # usually not repeated on the next attempt
                    self.logger.error(
                        f"LLM returned no answer text: model={self.model} "
                        f"finish_reason={choice.get('finish_reason')} "
                        f"usage={response_json.get('usage')}"
                    )
                    raise ExternalServiceError(
                        "LLM returned an empty answer "
                        f"(finish_reason: {choice.get('finish_reason')})",
                        service="LLM",
                    )
                return text

            except httpx.HTTPStatusError as e:
                self._raise_for_status(e)
            except httpx.RequestError as e:
                # str(e) is empty for httpx timeouts: always name the exception type
                detail = f"{type(e).__name__}: {str(e) or '(no message)'}"
                self.logger.error(f"Request error occurred: {detail}")
                raise ServiceUnavailableError(
                    f"LLM service unreachable: {detail}", service="LLM"
                ) from e

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

                payload = self._base_payload(messages)
                payload["stream"] = True

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
                                        text = extract_text(
                                            chunk["choices"][0]["delta"]["content"]
                                        )
                                        if text:
                                            yield text
                                except json.JSONDecodeError:
                                    # Skip invalid JSON lines
                                    continue

            except httpx.HTTPStatusError as e:
                self._raise_for_status(e)
            except httpx.RequestError as e:
                # str(e) is empty for httpx timeouts: always name the exception type
                detail = f"{type(e).__name__}: {str(e) or '(no message)'}"
                self.logger.error(f"Request error occurred: {detail}")
                raise ServiceUnavailableError(
                    f"LLM service unreachable: {detail}", service="LLM"
                ) from e

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
