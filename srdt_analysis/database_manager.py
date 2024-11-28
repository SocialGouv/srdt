import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional, Tuple

import asyncpg

from srdt_analysis.models import Document, DocumentsList


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

    async def fetch_articles_code_du_travail(self) -> DocumentsList:
        return await self.fetch_documents_by_source("code_du_travail")

    async def fetch_fiches_mt(self) -> DocumentsList:
        return await self.fetch_documents_by_source("page_fiche_ministere_travail")

    async def fetch_fiches_sp(self) -> DocumentsList:
        return await self.fetch_documents_by_source("fiches_service_public")

    async def fetch_page_infos(self) -> DocumentsList:
        return await self.fetch_documents_by_source("information")

    async def fetch_page_contribs(self) -> DocumentsList:
        return await self.fetch_documents_by_source("contributions")

    async def fetch_all(
        self,
    ) -> Tuple[
        DocumentsList, DocumentsList, DocumentsList, DocumentsList, DocumentsList
    ]:
        try:
            results = await asyncio.gather(
                self.fetch_articles_code_du_travail(),
                self.fetch_fiches_mt(),
                self.fetch_fiches_sp(),
                self.fetch_page_infos(),
                self.fetch_page_contribs(),
            )
            return (
                results[0],
                results[1],
                results[2],
                results[3],
                results[4],
            )
        finally:
            await self.close()


def get_data() -> (
    Tuple[DocumentsList, DocumentsList, DocumentsList, DocumentsList, DocumentsList]
):
    db = DatabaseManager()
    return asyncio.run(db.fetch_all())
