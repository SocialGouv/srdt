import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Literal, Optional, TypedDict

import asyncpg

CollectionName = Literal[
    "code_du_travail",
    "fiches_service_public",
    "page_fiche_ministere_travail",
    "information",
]

ChunkerContentType = Literal["markdown", "html", "character_recursive"]


ID = str
HTML = str
PlainText = str
JSONDict = Dict[str, Any]
Timestamp = datetime
URL = str
FormattedTextContent = str
COLLECTION_ID = str
COLLECTIONS_ID = list[str]
XML_AS_JSON = dict


@dataclass
class SplitDocument:
    page_content: str
    metadata: Dict[str, Any]


@dataclass
class DocumentData(TypedDict):
    cdtn_id: ID
    initial_id: ID
    title: PlainText
    content: PlainText
    url: URL
    source: CollectionName
    content_chunked: list[SplitDocument]


ListOfDocumentData = list[DocumentData]


@dataclass
class ResultProcessDocumentType(TypedDict):
    documents: list[DocumentData]
    id: str


@dataclass
class Reference:
    id: ID
    cid: ID
    url: URL
    slug: str
    type: str
    title: PlainText


@dataclass
class Section:
    html: HTML
    text: PlainText
    title: PlainText
    anchor: str
    references: list[Reference]
    description: PlainText
    htmlWithGlossary: HTML


@dataclass
class Content:
    text: str
    html: str
    sections: Optional[list[Section]]
    referencedTexts: Optional[list[Dict]]
    intro: str
    date: str
    url: str
    raw: str


@dataclass
class Document:
    cdtn_id: ID
    initial_id: ID
    title: PlainText
    meta_description: PlainText
    source: CollectionName
    slug: str
    text: PlainText
    document: JSONDict
    is_published: bool
    is_searchable: bool
    created_at: Timestamp
    updated_at: Timestamp
    is_available: bool
    content: Optional[Content] = None

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "Document":
        doc_data = json.loads(record["document"]) if record["document"] else {}
        content = None
        if doc_data:
            content = Content(
                text=doc_data.get("text", ""),
                html=doc_data.get("html", ""),
                intro=doc_data.get("intro", ""),
                date=doc_data.get("date", ""),
                sections=doc_data.get("sections", []),
                url=doc_data.get("url", ""),
                raw=doc_data.get("raw", ""),
                referencedTexts=doc_data.get("referencedTexts", []),
            )

        return cls(
            cdtn_id=record["cdtn_id"],
            initial_id=record["initial_id"],
            title=record["title"],
            meta_description=record["meta_description"],
            source=record["source"],
            slug=record["slug"],
            text=record["text"],
            document=doc_data,
            is_published=record["is_published"],
            is_searchable=record["is_searchable"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
            is_available=record["is_available"],
            content=content,
        )


DocumentsList = list[Document]


# Chunk
@dataclass
class ChunkMetadata(TypedDict):
    collection_id: ID
    document_id: ID
    document_name: PlainText
    document_part: int
    document_created_at: int
    id: ID
    source: CollectionName
    url: str
    collection: str


@dataclass
class Chunk(TypedDict):
    object: str
    id: str
    metadata: ChunkMetadata
    content: str


@dataclass
class RAGChunkData(TypedDict):
    score: float
    chunk: Chunk


@dataclass
class RAGChunkSearchResult(TypedDict):
    object: str
    data: list[RAGChunkData]


@dataclass
class RAGChunkDataEnriched(TypedDict):
    score: float
    chunk: Chunk
    document: Document
    content: str


@dataclass
class RAGChunkSearchResultEnriched(TypedDict):
    object: str
    data: list[RAGChunkDataEnriched]


# Albert Collection
@dataclass
class AlbertCollectionData(TypedDict):
    id: str
    name: str
    type: str
    model: Optional[str]
    user: Optional[str]
    description: Optional[str]
    created_at: Optional[int]
    documents: Optional[Any]


AlbertCollectionsList = list[AlbertCollectionData]
