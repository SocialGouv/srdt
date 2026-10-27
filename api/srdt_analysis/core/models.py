from dataclasses import dataclass
from typing import Literal, Sequence, TypedDict, Union

try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired

SourceName = Literal[
    "code_du_travail",
    "fiches_service_public",
    "page_fiche_ministere_travail",
    "information",
    "contributions",
    "contributions_idcc",
    "conventions",
    "judilibre",
]


CHUNK_ID = str


@dataclass
class RerankedChunk(TypedDict):
    relevance_score: float
    index: int


# LLM
class SystemLLMMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class UserLLMMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class LLMChatPayload(TypedDict):
    model: str
    messages: Sequence[Union[SystemLLMMessage, UserLLMMessage]]
    stream: NotRequired[bool]
    temperature: NotRequired[float]
