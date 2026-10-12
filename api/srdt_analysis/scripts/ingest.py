from typing import Callable

from dotenv import load_dotenv

from srdt_analysis.clients.elastic_handler import ElasticIndicesHandler
from srdt_analysis.clients.postgresql_manager import get_data
from srdt_analysis.core.constants import CHUNK_INDEX
from srdt_analysis.core.logger import Logger
from srdt_analysis.core.models import (
    Chunk,
    ChunkerContentType,
    CollectionName,
    DocumentsList,
)
from srdt_analysis.ingestion.agreements import get_conventions_chunked
from srdt_analysis.ingestion.data_exploiter_embed import (
    BaseDataExploiter,
    FichesMTExploiter,
    FichesSPExploiter,
    PageInfosExploiter,
    PagesContributionsExploiter,
)
from srdt_analysis.ingestion.judilibre import get_judilibre_chunked
from srdt_analysis.ingestion.legi_data import (
    LegiIndex,
    get_legi_data_chunked,
    load_legi_code,
)

load_dotenv()

logger = Logger("Ingester")

# Sources to (re)ingest: comment out the ones to keep as they are.
# Chunks of unselected sources are copied from the current index.
SELECTED_SOURCES: list[CollectionName] = [
    "contributions",
    "contributions_idcc",
    "information",
    "page_fiche_ministere_travail",
    "fiches_service_public",
    "code_du_travail",
    "conventions",
    "judilibre",
]

# Sources read from Postgres: exploiter and chunker content type
POSTGRES_SOURCES: dict[
    CollectionName, tuple[type[BaseDataExploiter], ChunkerContentType]
] = {
    "contributions": (PagesContributionsExploiter, "html"),
    "contributions_idcc": (PagesContributionsExploiter, "html_contribs"),
    "information": (PageInfosExploiter, "markdown"),
    "page_fiche_ministere_travail": (FichesMTExploiter, "html"),
    "fiches_service_public": (FichesSPExploiter, "character_recursive"),
}

# Sources read from files (except code du travail, which depends on the LEGI file)
FILE_SOURCES: dict[CollectionName, Callable[[], list[Chunk]]] = {
    "conventions": get_conventions_chunked,
    "judilibre": get_judilibre_chunked,
}


def start(sources: list[CollectionName] = SELECTED_SOURCES):
    logger.info(f"Ingest sources: {', '.join(sources)}")

    postgres_sources: list[CollectionName] = [
        s for s in sources if s in POSTGRES_SOURCES
    ]
    data: dict[CollectionName, DocumentsList] = {}
    if postgres_sources:
        logger.info("Read data from Postgres")
        data = get_data(postgres_sources)

    # the LEGI file is used to chunk the code du travail and to resolve links
    legi_code = None
    legi_index = None
    if postgres_sources or "code_du_travail" in sources:
        logger.info("Load legi data")
        legi_code = load_legi_code()
        legi_index = LegiIndex(legi_code)

    chunks_by_source: dict[CollectionName, list[Chunk]] = {}
    for source in sources:
        logger.info(f"Chunk {source}")
        if source in POSTGRES_SOURCES:
            exploiter_class, content_type = POSTGRES_SOURCES[source]
            chunks_by_source[source] = exploiter_class(legi_index).process_documents(
                data[source], content_type
            )
        elif source == "code_du_travail":
            chunks_by_source[source] = get_legi_data_chunked(legi_code)
        else:
            chunks_by_source[source] = FILE_SOURCES[source]()

    logger.info("Reingest corpus")

    index = ElasticIndicesHandler()

    index_name = CHUNK_INDEX

    alias = index.init_index_default(index_name)

    index.copy_other_sources(index_name, alias, list(sources))

    for source, chunks in chunks_by_source.items():
        logger.info(f"Index {len(chunks)} chunks from {source}")
        index.add_items(alias, chunks)

    index.swap_aliases(index_name, alias)


if __name__ == "__main__":
    start()
