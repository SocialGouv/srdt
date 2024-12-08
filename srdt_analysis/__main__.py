from dotenv import load_dotenv

from srdt_analysis.collections import Collections
from srdt_analysis.data_exploiter import PageInfosExploiter
from srdt_analysis.database_manager import get_data

load_dotenv()


def main():
    data = get_data(["information"])
    exploiter = PageInfosExploiter()
    result = exploiter.process_documents(
        [data["information"][0]], "page_infos.csv", "cdtn_page_infos"
    )
    collections = Collections()
    res = collections.search(
        "combien de jour de congé payé par mois de travail effectif",
        [result["id"]],
    )

    print(res)


if __name__ == "__main__":
    main()
