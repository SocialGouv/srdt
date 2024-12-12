from dotenv import load_dotenv

from srdt_analysis.collections import Collections
from srdt_analysis.data_exploiter import (
    ArticlesCodeDuTravailExploiter,
    FichesMTExploiter,
    FichesSPExploiter,
    PageInfosExploiter,
)
from srdt_analysis.database_manager import get_data
from srdt_analysis.llm_processor import LLMProcessor
from srdt_analysis.mapper import Mapper

load_dotenv()

QUESTION = "Combien de jours de congé payé par mois de travail effectif ?"
COLLECTION_IDS = [
    "4462ceb9-6da9-4f76-8a63-b87d4cc5afa0",  # information
    "fa1d5d19-ec81-493a-843d-b33ce438f630",  # page_fiche_ministere_travail
    "ba380a00-660b-4b49-8a77-7b8b389c3200",  # code_du_travail
    "8dfca31c-994b-41cd-b5d5-c12231eee5d9",  # fiches_service_public
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
        ]
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
