import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

import asyncpg

ID = str
HTML = str
PlainText = str
JSONDict = Dict[str, Any]
Timestamp = datetime
URL = str


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
    keywords: PlainText
    summary: PlainText
    questions: PlainText
    url: URL
    content_chunked: List[SplitDocument]


@dataclass
class ResultProcessDocumentType(TypedDict):
    documents: List[DocumentData]
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
    references: List[Reference]
    description: PlainText
    htmlWithGlossary: HTML


@dataclass
class Content:
    text: str
    html: str
    sections: Optional[List[Section]]
    referencedTexts: Optional[List[Dict]]
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
    source: str
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


DocumentsList = List[Document]


# Chunk
@dataclass
class ChunkMetadata:
    collection_id: ID
    document_id: ID
    document_name: PlainText
    document_part: int
    document_created_at: int
    structure_du_chunk: Dict[str, str]
    cdtn_id: ID
    collection: str


@dataclass
class Chunk:
    object: str
    id: str
    metadata: ChunkMetadata
    content: str


@dataclass
class ChunkDataItem:
    score: float
    chunk: Chunk


@dataclass
class ChunkDataList:
    object: str
    data: List[ChunkDataItem]
