from srdt_analysis.collections import Collections
from srdt_analysis.constants import (
    LLM_ANONYMIZATION_PROMPT,
    LLM_REPHRASING_PROMPT,
    LLM_SPLIT_MULTIPLE_QUERIES_PROMPT,
)
from srdt_analysis.database_manager import DatabaseManager
from srdt_analysis.llm_processor import LLMProcessor
from srdt_analysis.mapper import Mapper
from srdt_analysis.models import (
    CollectionName,
    LLMMessageSecurized,
    RAGChunkSearchResult,
    RAGChunkSearchResultEnriched,
)


class LLMRunner:
    def __init__(self):
        self.collections = Collections()
        self.llm_processor = LLMProcessor()
        self.db_manager = DatabaseManager()
        self.mapper = None

    async def initialize(self, sources: list[CollectionName]):
        if self.mapper is None:
            self.data = await self.db_manager.fetch_sources(sources)
            self.mapper = Mapper(self.data)

    async def anonymize(
        self,
        user_message: str,
        optional_prompt: str | None = None,
    ) -> str:
        prompt = (
            optional_prompt if optional_prompt is not None else LLM_ANONYMIZATION_PROMPT
        )
        result = await self.llm_processor.get_completions_async(prompt, user_message)
        return result

    async def rephrase_and_split(
        self,
        question: str,
        optional_rephrasing_prompt: str | None = None,
        optional_queries_splitting_prompt: str | None = None,
    ) -> tuple[str, list[str] | None]:
        rephrasing_prompt = (
            optional_rephrasing_prompt
            if optional_rephrasing_prompt is not None
            else LLM_REPHRASING_PROMPT
        )
        queries_splitting_prompt = (
            optional_queries_splitting_prompt
            if optional_queries_splitting_prompt is not None
            else LLM_SPLIT_MULTIPLE_QUERIES_PROMPT
        )
        rephrased_question = await self.llm_processor.get_completions_async(
            rephrasing_prompt, question
        )

        queries = await self.llm_processor.get_completions_async(
            queries_splitting_prompt, rephrased_question
        )

        query_list = [q.strip() for q in queries.split("\n") if q.strip()]

        return rephrased_question, query_list

    async def chat_with_full_document(
        self,
        chat_history: list[LLMMessageSecurized],
        prompt: str,
        collection_ids: list[str],
        sources: list[CollectionName],
    ) -> tuple[str, RAGChunkSearchResult]:
        if self.mapper is None:
            await self.initialize(sources)

        result = ""
        last_message = chat_history[-1]
        rag_response = self.collections.search(
            last_message["content"],
            collection_ids,
        )
        if self.mapper is None:
            raise ValueError("Mapper not initialized")

        data_to_send_to_llm = self.mapper.get_original_docs(rag_response)

        async for token in self.llm_processor.get_chat_completions_stream_async(
            chat_history,
            prompt,
            data_to_send_to_llm,
        ):
            result += token
        return result, rag_response

    async def chat_with_rag_data(
        self,
        chat_history: list[LLMMessageSecurized],
        prompt: str,
        data_to_send_to_llm: RAGChunkSearchResultEnriched,
    ) -> tuple[str, RAGChunkSearchResultEnriched]:
        result = ""
        async for token in self.llm_processor.get_chat_completions_stream_async(
            chat_history,
            prompt,
            data_to_send_to_llm,
        ):
            result += token
        return result, data_to_send_to_llm
