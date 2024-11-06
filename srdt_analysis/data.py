import os
import asyncpg
import asyncio


async def fetch_articles_code_du_travail(
    conn,
):
    results = await conn.fetch(
        "SELECT * from public.documents WHERE source = 'code_du_travail'"
    )
    return results


async def fetch_fiches_mt(
    conn,
):
    result = await conn.fetch(
        "SELECT * from public.documents WHERE source = 'page_fiche_ministere_travail'"
    )
    return result


async def fetch_fiches_sp(
    conn,
):
    result = await conn.fetch(
        "SELECT * from public.documents WHERE source = 'fiches_service_public'"
    )
    return result


async def fetch_page_infos(
    conn,
):
    result = await conn.fetch(
        "SELECT * from public.documents WHERE source = 'information'"
    )
    return result


async def fetch_page_contribs(
    conn,
):
    result = await conn.fetch(
        "SELECT * from public.documents WHERE source = 'contributions'"
    )
    return result


async def run():
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


def get_data():
    return asyncio.run(run())
