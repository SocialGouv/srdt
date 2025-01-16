from typing import Optional, Tuple

from srdt_analysis.collections import AlbertCollectionHandler
from srdt_analysis.constants import (
    LLM_ANONYMIZATION_PROMPT,
    LLM_ANSWER_PROMPT,
    LLM_REPHRASING_PROMPT,
    LLM_SPLIT_MULTIPLE_QUERIES_PROMPT,
)
from srdt_analysis.llm_client import LLMClient
from srdt_analysis.models import (
    UserLLMMessage,
)


class LLMRunner:
    collections: AlbertCollectionHandler
    llm_processor: LLMClient

    def __init__(self, llm_url: str, llm_api_token: str, llm_model: str):
        self.collections = AlbertCollectionHandler()
        self.llm_processor = LLMClient(llm_url, llm_api_token, llm_model)

    async def anonymize(
        self,
        user_message: str,
        optional_prompt: Optional[str] = None,
    ) -> str:
        prompt = (
            optional_prompt if optional_prompt is not None else LLM_ANONYMIZATION_PROMPT
        )
        result = await self.llm_processor.generate_completions_async(
            prompt,
            [UserLLMMessage(role="user", content=user_message)],
        )
        return result

    async def rephrase_and_split(
        self,
        question: str,
        rephrasing_prompt: Optional[str] = None,
        queries_splitting_prompt: Optional[str] = None,
    ) -> Tuple[str, Optional[list[str]]]:
        rephrasing_prompt = (
            rephrasing_prompt
            if rephrasing_prompt is not None
            else LLM_REPHRASING_PROMPT
        )
        queries_splitting_prompt = (
            queries_splitting_prompt
            if queries_splitting_prompt is not None
            else LLM_SPLIT_MULTIPLE_QUERIES_PROMPT
        )
        rephrased_question = await self.llm_processor.generate_completions_async(
            rephrasing_prompt,
            [UserLLMMessage(role="user", content=question)],
        )

        queries = await self.llm_processor.generate_completions_async(
            queries_splitting_prompt,
            [UserLLMMessage(role="user", content=rephrased_question)],
        )

        query_list = [q.strip() for q in queries.split("\n") if q.strip()]

        return rephrased_question, query_list

    async def chat_with_full_document(
        self,
        chat_history: list[UserLLMMessage],
        system_prompt: Optional[str] = None,
    ) -> str:
        system_prompt = (
            system_prompt if system_prompt is not None else LLM_ANSWER_PROMPT
        )
        return await self.llm_processor.generate_completions_async(
            system_prompt,
            chat_history,
        )
