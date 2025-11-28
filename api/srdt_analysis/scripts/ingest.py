import os

import pandas as pd
from dotenv import load_dotenv

from srdt_analysis.elastic_handler import ElasticIndicesHandler
from srdt_analysis.data_exploiter_embed import (
    FichesMTExploiter,
    FichesSPExploiter,
    PageInfosExploiter,
    PagesContributionsExploiter,
)
from srdt_analysis.legi_data import get_legi_data_chunked
from srdt_analysis.logger import Logger
from srdt_analysis.postgresql_manager import get_data
from srdt_analysis.sparse import preprocess

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

    if os.getenv("INGEST", "False") == "True":
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

    if os.getenv("CREATE_PARQUET", "False") == "True":
        logger.info("Create Parquet files")

        all_docs = pd.DataFrame(
            [
                *page_contribs,
                *page_contribs_idcc,
                *page_infos,
                *fiche_mt,
                *articles_code_du_travail,
                *page_sp,
            ]
        )

        metadata = all_docs.rename({"cdtn_id": "document_id"}, axis="columns")[
            ["url", "title", "document_id", "source", "idcc"]
        ].to_dict(
            "records"
        )  # type: ignore

        chunks_content = all_docs["content_chunked"].apply(
            lambda x: [sd.page_content for sd in x]
        )

        chunks = pd.DataFrame(
            {
                "cdtn_id": all_docs.cdtn_id,
                "metadata": metadata,
                "content": chunks_content,
                "idcc": all_docs["idcc"],
            }
        ).explode("content")

        chunks["index_in_doc"] = chunks.groupby("cdtn_id").cumcount()
        # reset index then set it as a column
        chunks.reset_index(inplace=True, drop=True)
        chunks.reset_index(inplace=True)
        chunks.rename({"index": "id_chunk"}, axis="columns", inplace=True)

        all_docs["content_chunked"] = chunks_content
        all_docs["sparse_prepro"] = all_docs.apply(
            lambda x: preprocess([x.title] + x.content_chunked), axis=1
        )

        all_docs.to_parquet(f"{os.getenv('PARQUET_OUTPUT_PATH')}/docs.parquet")
        chunks.to_parquet(f"{os.getenv('PARQUET_OUTPUT_PATH')}/chunks.parquet")


if __name__ == "__main__":
    start()
