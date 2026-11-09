"""CDTN documents (contributions, fiches, information pages) read from the
`public.documents` table of the CDTN database."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from ingestion.contract import SourceName
from ingestion.settings import Settings, secret


@dataclass
class Document:
    cdtn_id: str
    initial_id: str
    title: str
    source: SourceName
    slug: str
    text: str
    document: dict[str, Any]
    updated_at: datetime
    idcc: str | None = None

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "Document":
        doc_data = json.loads(record["document"]) if record["document"] else {}
        return cls(
            cdtn_id=record["cdtn_id"],
            initial_id=record["initial_id"],
            title=record["title"],
            source=record["source"],
            slug=record["slug"],
            text=record["text"],
            document=doc_data,
            updated_at=record["updated_at"],
            idcc=doc_data.get("idcc", None) if doc_data else None,
        )


async def _fetch_source(pool: asyncpg.Pool, source: SourceName) -> list[Document]:
    query = """
        SELECT * from public.documents
        WHERE source = $1
        AND is_published = true
        AND is_available = true
    """
    # contributions are split on the generic one (idcc 0000) vs the ones of a
    # collective agreement
    if source == "contributions":
        query += " AND document->>'content' IS NOT NULL AND document->>'idcc' = '0000'"
    if source == "contributions_idcc":
        query += " AND document->>'content' IS NOT NULL AND document->>'idcc' != '0000'"

    async with pool.acquire() as conn:
        records = await conn.fetch(
            query, "contributions" if source == "contributions_idcc" else source
        )
    documents = [Document.from_record(r) for r in records]
    if source == "contributions_idcc":
        for doc in documents:
            doc.source = source
    return documents


async def _fetch_sources(
    settings: Settings, sources: Sequence[SourceName]
) -> dict[SourceName, list[Document]]:
    settings.require("postgres_user", "postgres_database_url")
    pool = await asyncpg.create_pool(
        user=settings.postgres_user,
        password=secret(settings.postgres_password),
        database=settings.postgres_database_name,
        host=settings.postgres_database_url,
    )
    try:
        results = await asyncio.gather(*(_fetch_source(pool, s) for s in sources))
        return dict(zip(sources, results, strict=True))
    finally:
        await pool.close()


def load_documents(
    settings: Settings, sources: Sequence[SourceName]
) -> dict[SourceName, list[Document]]:
    return asyncio.run(_fetch_sources(settings, sources))
