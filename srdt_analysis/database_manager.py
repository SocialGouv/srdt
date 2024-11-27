import asyncio
import os
from typing import Tuple

import asyncpg

from srdt_analysis.models import Document, DocumentsList


class DatabaseManager:
    def __init__(self):
        self.conn

    async def connect(self):
        self.conn = await asyncpg.connect(
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            database=os.getenv("POSTGRES_DATABASE_NAME"),
            host=os.getenv("POSTGRES_DATABASE_URL"),
        )

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def fetch_articles_code_du_travail(self) -> DocumentsList:
        results = await self.conn.fetch(
            "SELECT * from public.documents WHERE source = 'code_du_travail'"
        )
        return [Document.from_record(r) for r in results]

    async def fetch_fiches_mt(self) -> DocumentsList:
        result = await self.conn.fetch(
            "SELECT * from public.documents WHERE source = 'page_fiche_ministere_travail'"
        )
        return [Document.from_record(r) for r in result]

    async def fetch_fiches_sp(self) -> DocumentsList:
        result = await self.conn.fetch(
            "SELECT * from public.documents WHERE source = 'fiches_service_public'"
        )
        return [Document.from_record(r) for r in result]

    async def fetch_page_infos(self) -> DocumentsList:
        result = await self.conn.fetch(
            "SELECT * from public.documents WHERE source = 'information'"
        )
        return [Document.from_record(r) for r in result]

    async def fetch_page_contribs(self) -> DocumentsList:
        result = await self.conn.fetch(
            "SELECT * from public.documents WHERE source = 'contributions'"
        )
        return [Document.from_record(r) for r in result]

    async def fetch_all(
        self,
    ) -> Tuple[
        DocumentsList,
        DocumentsList,
        DocumentsList,
        DocumentsList,
        DocumentsList,
    ]:
        await self.connect()

        result1 = await self.fetch_articles_code_du_travail()
        result2 = await self.fetch_fiches_mt()
        result3 = await self.fetch_fiches_sp()
        result4 = await self.fetch_page_infos()
        result5 = await self.fetch_page_contribs()

        await self.close()

        return (result1, result2, result3, result4, result5)


def get_data() -> (
    Tuple[
        DocumentsList,
        DocumentsList,
        DocumentsList,
        DocumentsList,
        DocumentsList,
    ]
):
    db = DatabaseManager()
    return asyncio.run(db.fetch_all())
