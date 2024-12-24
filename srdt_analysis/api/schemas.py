from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from srdt_analysis.models import LLMMessageSecurized, RAGChunkSearchResultEnriched


class AnonymizeRequest(BaseModel):
    user_question: str
    anonymization_prompt: Optional[str] = None  # TODO : to be removed in the future


class AnonymizeResponse(BaseModel):
    time: float
    anonymized_question: str
    nb_token_input: int
    nb_token_output: int


class RephraseRequest(BaseModel):
    question: str
    rephrasing_prompt: str  # TODO : to be removed in the future
    queries_splitting_prompt: Optional[str] = None  # TODO : to be removed in the future


class RephraseResponse(BaseModel):
    time: float
    rephrased_question: str
    queries: Optional[List[str]] = None
    nb_token_input: int
    nb_token_output: int


class SearchOptions(BaseModel):
    top_K: Optional[int] = Field(default=5)
    threshold: Optional[float] = Field(default=0.0, ge=0.0, le=1.0)
    collections: Optional[List[str]] = None


class SearchRequest(BaseModel):
    prompts: List[str]
    options: Optional[SearchOptions] = None


class ChunkMetadata(BaseModel):
    title: str
    url: str
    document_id: str
    source: str


class ChunkResult(BaseModel):
    score: float
    content: str
    id_chunk: str
    metadata: ChunkMetadata


class SearchResponse(BaseModel):
    time: float
    top_chunks: List[ChunkResult]


class GenerateRequest(BaseModel):
    chat_history: List[LLMMessageSecurized]
    system_prompt: str
    chunks: Optional[RAGChunkSearchResultEnriched] = None
    context_insertion_method: Literal["chunk", "full_document"] = "full_document"


class GenerateResponse(BaseModel):
    time: float
    text: str
    nb_token_input: int
    nb_token_output: int
    sources: List[str]
