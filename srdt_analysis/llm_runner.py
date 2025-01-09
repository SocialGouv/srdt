from srdt_analysis.collections import AlbertCollectionHandler
from srdt_analysis.constants import (
    LLM_ANONYMIZATION_PROMPT,
    LLM_REPHRASING_PROMPT,
    LLM_SPLIT_MULTIPLE_QUERIES_PROMPT,
)
from srdt_analysis.database_manager import PostgreSQLManager
from srdt_analysis.llm_processor import LLMProcessor
from srdt_analysis.mapper import Mapper
from srdt_analysis.models import (
    CollectionName,
    RAGChunkSearchResult,
    EnrichedRAGSearchResultChunks,
    UserLLMMessage,
)


class LLMRunner:
    def __init__(self):
        self.collections = AlbertCollectionHandler()
        self.llm_processor = LLMProcessor()
        self.db_manager = PostgreSQLManager()
        self.mapper = None

    async def initialize(self, sources: list[CollectionName]):
        if self.mapper is None:
            self.data_sources = await self.db_manager.fetch_sources(sources)
            self.mapper = Mapper(self.data_sources)

    async def anonymize(
        self,
        user_message: str,
        optional_prompt: str | None = None,
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
        prompt: str,
        collection_ids: list[str],
        sources: list[CollectionName],
    ) -> tuple[str, RAGChunkSearchResult]:
        if self.mapper is None:
            await self.initialize(sources)

        result = ""
        last_message = chat_history[-1]
        found_chunks = self.collections.search(
            last_message["content"],
            collection_ids,
        )
        if self.mapper is None:
            raise ValueError("Mapper not initialized")

        enriched_search_result_chunk = self.mapper.get_original_docs(found_chunks)

        result = await self.chat_using_chunks(
            chat_history=chat_history,
            prompt=prompt,
            enriched_search_result_chunk=enriched_search_result_chunk,
        )

        return result, found_chunks

    async def chat_using_chunks(
        self,
        chat_history: list[UserLLMMessage],
        prompt: str,
        enriched_search_result_chunk: EnrichedRAGSearchResultChunks,
    ) -> str:
        result = ""
        async for token in self.llm_processor.generate_chat_completions_stream_async(
            prompt,
            chat_history,
            enriched_search_result_chunk,
        ):
            result += token
        return result
