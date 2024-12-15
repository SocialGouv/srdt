from dotenv import load_dotenv

from srdt_analysis.collections import Collections
from srdt_analysis.data_exploiter import (
    ArticlesCodeDuTravailExploiter,
    FichesMTExploiter,
    FichesSPExploiter,
    PageInfosExploiter,
    PagesContributionsExploiter,
)
from srdt_analysis.database_manager import get_data
from srdt_analysis.llm_processor import LLMProcessor
from srdt_analysis.mapper import Mapper

load_dotenv()

QUESTION = "Combien de jours de congé payé par mois de travail effectif ?"
COLLECTION_IDS = [
    "5755cf5f-1cb5-4ec6-a076-21047d069578",  # information
    "0576c752-f097-403e-b2be-d6d806c3848a",  # page_fiche_ministere_travail
    "0be5059b-762f-48ba-a8f0-fe10e81455c8",  # code_du_travail
    "f8d66426-5c54-4503-aa30-a3abc19453d5",  # fiches_service_public
    "d03df69b-9387-4359-80db-7d73f2b6f04a",  # contributions
]


def main():
    ingest()


def ingest():
    data = get_data(
        [
            "information",
            "code_du_travail",
            "page_fiche_ministere_travail",
            "fiches_service_public",
            "contributions",
        ]
    )
    page_contribs_exploiter = PagesContributionsExploiter()
    page_contribs_exploiter.process_documents(
        data["contributions"], "contributions", "html"
    )
    page_infos_exploiter = PageInfosExploiter()
    page_infos_exploiter.process_documents(
        data["information"], "information", "markdown"
    )
    fiche_mt_exploiter = FichesMTExploiter()
    fiche_mt_exploiter.process_documents(
        data["page_fiche_ministere_travail"], "page_fiche_ministere_travail", "html"
    )
    article_code_du_travail_exploiter = ArticlesCodeDuTravailExploiter()
    article_code_du_travail_exploiter.process_documents(
        data["code_du_travail"], "code_du_travail", "character_recursive"
    )
    page_sp_exploiter = FichesSPExploiter()
    page_sp_exploiter.process_documents(
        data["fiches_service_public"], "fiches_service_public", "character_recursive"
    )


def run_llm():
    data = get_data(
        [
            "information",
            "code_du_travail",
            "page_fiche_ministere_travail",
            "fiches_service_public",
        ]
    )
    collections = Collections()
    rag_response = collections.search(
        QUESTION,
        COLLECTION_IDS,
    )
    mapper = Mapper(data)
    data_to_send_to_llm = mapper.get_original_docs(rag_response)
    llm_processor = LLMProcessor()
    for token in llm_processor.get_answer_stream(
        QUESTION,
        data_to_send_to_llm,
    ):
        print(token, end="", flush=True)


if __name__ == "__main__":
    main()
