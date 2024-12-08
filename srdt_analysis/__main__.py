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


def main():
    data = get_data(
        [
            "information",
            "code_du_travail",
            "page_fiche_ministere_travail",
            "fiches_service_public",
        ]
    )
    collections = Collections()
    page_infos_exploiter = PageInfosExploiter()
    result_page_info = page_infos_exploiter.process_documents(
        data["information"], "information", "markdown"
    )
    fiche_mt_exploiter = FichesMTExploiter()
    result_fiche_mt = fiche_mt_exploiter.process_documents(
        data["page_fiche_ministere_travail"], "page_fiche_ministere_travail", "html"
    )
    article_code_du_travail_exploiter = ArticlesCodeDuTravailExploiter()
    result_article_code_du_travail = (
        article_code_du_travail_exploiter.process_documents(
            data["code_du_travail"], "code_du_travail", "character_recursive"
        )
    )
    page_sp_exploiter = FichesSPExploiter()
    result_page_sp = page_sp_exploiter.process_documents(
        data["fiches_service_public"], "fiches_service_public", "character_recursive"
    )
    rag_response = collections.search(
        QUESTION,
        [
            result_page_info["id"],
            result_fiche_mt["id"],
            result_page_sp["id"],
            result_article_code_du_travail["id"],
        ],
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
