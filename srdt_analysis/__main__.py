from dotenv import load_dotenv

from srdt_analysis.data import get_data
from srdt_analysis.exploit_data import PageInfosExploiter

load_dotenv()


def main():
    data = get_data()
    exploiter = PageInfosExploiter()
    exploiter.process_documents([data[3][0]], "page_infos.csv")


if __name__ == "__main__":
    main()
