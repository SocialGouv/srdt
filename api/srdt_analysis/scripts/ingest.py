from dotenv import load_dotenv

from srdt_analysis.data_exploiter_embed import (
    FichesMTExploiter,
    FichesSPExploiter,
    PageInfosExploiter,
    PagesContributionsExploiter,
)
from srdt_analysis.elastic_handler import ElasticIndicesHandler
from srdt_analysis.legi_data import get_legi_data_chunked
from srdt_analysis.logger import Logger
from srdt_analysis.postgresql_manager import get_data

load_dotenv()

logger = Logger("Ingester")


def start():
    logger.info("Read data from Postgres")
    data = get_data(
        [
            "information",
            "page_fiche_ministere_travail",
            "fiches_service_public",
            "contributions",
            "contributions_idcc",
        ]
    )

    page_contribs_exploiter = PagesContributionsExploiter()
    page_contribs = page_contribs_exploiter.process_documents(
        data["contributions"], "html"
    )

    page_contribs_idcc_exploiter = PagesContributionsExploiter()
    page_contribs_idcc = page_contribs_idcc_exploiter.process_documents(
        data["contributions_idcc"], "html"
    )

    page_infos_exploiter = PageInfosExploiter()
    page_infos = page_infos_exploiter.process_documents(data["information"], "markdown")

    fiche_mt_exploiter = FichesMTExploiter()
    fiche_mt = fiche_mt_exploiter.process_documents(
        data["page_fiche_ministere_travail"], "html"
    )

    articles_code_du_travail = get_legi_data_chunked()

    page_sp_exploiter = FichesSPExploiter()
    page_sp = page_sp_exploiter.process_documents(
        data["fiches_service_public"], "character_recursive"
    )

    logger.info("Reingest corpus")

    index = ElasticIndicesHandler()

    index_name = "chunks"

    alias = index.init_index_default(index_name)

    for docs in [
        page_contribs,
        page_contribs_idcc,
        page_infos,
        fiche_mt,
        page_sp,
        articles_code_du_travail,
    ]:
        index.add_items(alias, docs)

    index.swap_aliases(index_name, alias)


if __name__ == "__main__":
    start()
