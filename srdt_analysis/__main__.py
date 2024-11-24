from dotenv import load_dotenv

from srdt_analysis.collections import Collections
from srdt_analysis.data import get_data
from srdt_analysis.exploit_data import PageInfosExploiter

load_dotenv()


def main():
    data = get_data()
    exploiter = PageInfosExploiter()
    result = exploiter.process_documents([data[3][0]], "page_infos.csv", "cdtn_page_infos")
    collections = Collections()
    res = collections.search("droit du travail", [result[1]])
    print(res["data"][0])


if __name__ == "__main__":
    main()
