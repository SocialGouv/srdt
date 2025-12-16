from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from srdt_analysis.constants import SOURCES
from srdt_analysis.models import (
    CHUNK_ID,
    CollectionName,
    UserLLMMessage,
)


class LLMModel(BaseModel):
    base_url: str
    name: str
    api_key: str


class AnonymizeRequest(BaseModel):
    user_question: str


class AnonymizeResponse(BaseModel):
    time: float
    anonymized_question: str
    nb_token_input: int
    nb_token_output: int


class RephraseRequest(BaseModel):
    model: LLMModel
    question: str
    rephrasing_prompt: Optional[str] = None  # TODO : to be removed in the future
    queries_splitting_prompt: Optional[str] = None  # TODO : to be removed in the future


class RephraseResponse(BaseModel):
    time: float
    rephrased_question: str
    queries: Optional[List[str]] = None
    nb_token_input: int
    nb_token_output: int


class SearchOptions(BaseModel):
    top_K: int = Field(default=20)
    threshold: float = Field(default=0, ge=0.0, le=2.0)
    collections: List[str] = Field(default=SOURCES)
    hybrid: Optional[bool] = False

    @field_validator("collections")
    @classmethod
    def validate_collections(cls, collections):
        if collections is not None:
            invalid_collections = [c for c in collections if c not in SOURCES]
            if invalid_collections:
                raise ValueError(
                    f"Invalid collection IDs: {invalid_collections}. Must be one of {SOURCES}"
                )
        return collections


class SearchRequest(BaseModel):
    prompts: List[str] = Field(max_length=10)
    options: SearchOptions = Field(default_factory=SearchOptions)
    idcc: Optional[str] = None

    @classmethod
    def model_validate(
        cls,
        obj,
        *,
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[dict] = None,
    ):
        if isinstance(obj, dict) and obj.get("options") is None:
            obj["options"] = {}
        return super().model_validate(
            obj, strict=strict, from_attributes=from_attributes, context=context
        )


class ChunkMetadata(BaseModel):
    title: str
    url: str
    id: str
    source: CollectionName
    idcc: Optional[str] = None


class ChunkResult(BaseModel):
    score: float
    content: str
    id_chunk: CHUNK_ID
    metadata: ChunkMetadata


class ContentResult(BaseModel):
    metadata: ChunkMetadata
    content: str


class RerankedChunk(BaseModel):
    rerank_score: float
    chunk: ChunkResult


class RerankRequest(BaseModel):
    prompt: str
    inputs: List[ChunkResult]


class SearchResponse(BaseModel):
    time: float
    top_chunks: List[ChunkResult]


class RetrieveRequest(BaseModel):
    ids: List[str]


class RetrieveResponse(BaseModel):
    time: float
    contents: List[ContentResult]


class RerankResponse(BaseModel):
    time: float
    results: List[RerankedChunk]


class GenerateRequest(BaseModel):
    model: LLMModel
    chat_history: List[UserLLMMessage]
    system_prompt: Optional[str] = None  # TODO : to be removed in the future


class GenerateResponse(BaseModel):
    time: float
    text: str
    nb_token_input: int
    nb_token_output: int
