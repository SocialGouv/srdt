from srdt_analysis.collections import Collections
from srdt_analysis.constants import (
    LLM_ANONYMIZATION_PROMPT,
)
from srdt_analysis.database_manager import DatabaseManager
from srdt_analysis.llm_processor import LLMProcessor
from srdt_analysis.mapper import Mapper
from srdt_analysis.models import (
    CollectionName,
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
