import os
import asyncpg
import asyncio
from typing import List, Tuple
from .models import Document, DocumentsList


async def fetch_articles_code_du_travail(
    conn: asyncpg.Connection,
) -> DocumentsList:
    results = await conn.fetch(
        "SELECT * from public.documents WHERE source = 'code_du_travail'"
    )
    return [Document.from_record(r) for r in results]


async def fetch_fiches_mt(
    conn: asyncpg.Connection,
) -> DocumentsList:
    result = await conn.fetch(
        "SELECT * from public.documents WHERE source = 'page_fiche_ministere_travail'"
    )
    return [Document.from_record(r) for r in result]


async def fetch_fiches_sp(
    conn: asyncpg.Connection,
) -> DocumentsList:
    result = await conn.fetch(
        "SELECT * from public.documents WHERE source = 'fiches_service_public'"
    )
    return [Document.from_record(r) for r in result]


async def fetch_page_infos(
    conn: asyncpg.Connection,
) -> DocumentsList:
    result = await conn.fetch(
        "SELECT * from public.documents WHERE source = 'information'"
    )
    return [Document.from_record(r) for r in result]


async def fetch_page_contribs(
    conn: asyncpg.Connection,
) -> DocumentsList:
    result = await conn.fetch(
        "SELECT * from public.documents WHERE source = 'contributions'"
    )
    return [Document.from_record(r) for r in result]


async def run() -> Tuple[
    DocumentsList,
    DocumentsList,
    DocumentsList,
    DocumentsList,
    DocumentsList,
]:
    conn = await asyncpg.connect(
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        database=os.getenv("POSTGRES_DATABASE_NAME"),
        host=os.getenv("POSTGRES_DATABASE_URL"),
    )

    result1 = await fetch_articles_code_du_travail(conn)
    result2 = await fetch_fiches_mt(conn)
    result3 = await fetch_fiches_sp(conn)
    result4 = await fetch_page_infos(conn)
    result5 = await fetch_page_contribs(conn)

    await conn.close()

    return (
        result1,
        result2,
        result3,
        result4,
        result5,
    )


def get_data() -> Tuple[
    DocumentsList,
    DocumentsList,
    DocumentsList,
    DocumentsList,
    DocumentsList,
]:
    return asyncio.run(run())
