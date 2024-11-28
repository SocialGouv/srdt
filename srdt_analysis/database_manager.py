import asyncio
import os
from contextlib import asynccontextmanager
from typing import List, Literal, Optional, Sequence

import asyncpg

from srdt_analysis.models import Document, DocumentsList

ListCollections = Literal[
    "code_du_travail",
    "fiches_service_public",
    "page_fiche_ministere_travail",
    "contributions",
    "information",
]


class DatabaseManager:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            database=os.getenv("POSTGRES_DATABASE_NAME"),
            host=os.getenv("POSTGRES_DATABASE_URL"),
        )

    async def close(self):
        if self.pool:
            await self.pool.close()

    @asynccontextmanager
    async def get_connection(self):
        if not self.pool:
            await self.connect()
        if self.pool is None:
            raise ValueError("Pool is not initialized")
        async with self.pool.acquire() as conn:
            yield conn

    async def fetch_documents_by_source(self, source: str) -> DocumentsList:
        async with self.get_connection() as conn:
            result = await conn.fetch(
                "SELECT * from public.documents WHERE source = $1", source
            )
            return [Document.from_record(r) for r in result]

    async def fetch_sources(
        self, sources: Sequence[ListCollections]
    ) -> dict[ListCollections, DocumentsList]:
        try:
            tasks = [self.fetch_documents_by_source(source) for source in sources]
            results = await asyncio.gather(*tasks)
            return {source: result for source, result in zip(sources, results)}
        finally:
            await self.close()


def get_data(
    sources: Sequence[ListCollections],
) -> dict[ListCollections, DocumentsList]:
    db = DatabaseManager()
    return asyncio.run(db.fetch_sources(sources))
