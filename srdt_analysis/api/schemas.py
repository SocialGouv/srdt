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
