from dotenv import load_dotenv

from srdt_analysis.data_exploiter import (
    ArticlesCodeDuTravailExploiter,
    FichesMTExploiter,
    FichesSPExploiter,
    PageInfosExploiter,
    PagesContributionsExploiter,
)
from srdt_analysis.postgresql_manager import get_data

load_dotenv()


def start():
    data = get_data(
        [
            "information",
            "code_du_travail",
            "page_fiche_ministere_travail",
            "fiches_service_public",
            "contributions",
            "contributions_idcc",
        ]
    )
    page_contribs_exploiter = PagesContributionsExploiter()
    page_contribs_exploiter.process_documents(
        data["contributions"], "contributions", "html"
    )
    
    page_contribs_idcc_exploiter = PagesContributionsExploiter()
    page_contribs_idcc_exploiter.process_documents(
        data["contributions_idcc"], "contributions_idcc", "html"
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


if __name__ == "__main__":
    start()
