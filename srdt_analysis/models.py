import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

import asyncpg


@dataclass
class SplitDocument:
    page_content: str
    metadata: Dict[str, Any]


@dataclass
class DocumentData(TypedDict):
    cdtn_id: str
    initial_id: str
    title: str
    content: str
    keywords: str
    summary: str
    questions: str
    vector_summary: dict
    vector_keywords: dict
    vector_questions: dict
    idcc: str
    chunks: List[SplitDocument]
    vector_chunks: List[dict]


@dataclass
class Reference:
    id: str
    cid: str
    url: str
    slug: str
    type: str
    title: str


@dataclass
class Section:
    html: str
    text: str
    title: str
    anchor: str
    references: List[Reference]
    description: str
    htmlWithGlossary: str


@dataclass
class Content:
    text: str
    html: str
    intro: str = ""
    date: str = ""
    sections: List[Section] = None
    url: str = ""
    raw: str = ""
    referencedTexts: List[Dict] = None


@dataclass
class Document:
    cdtn_id: str
    initial_id: str
    title: str
    meta_description: str
    source: str
    slug: str
    text: str
    document: Dict[str, Any]
    is_published: bool
    is_searchable: bool
    created_at: datetime
    updated_at: datetime
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
    collection_id: str
    document_id: str
    document_name: str
    document_part: int
    document_created_at: int
    structure_du_chunk: Dict[str, str]
    idcc: str
    cdtn_id: str
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