from dotenv import load_dotenv

from srdt_analysis.collections import Collections
from srdt_analysis.data_exploiter import PageInfosExploiter
from srdt_analysis.database_manager import get_data
from srdt_analysis.llm_processor import LLMProcessor
from srdt_analysis.mapper import Mapper

load_dotenv()


def main():
    data = get_data(["information"])
    exploiter = PageInfosExploiter()
    result = exploiter.process_documents([data["information"][0]], "cdtn_page_infos")
    collections = Collections()
    rag_response = collections.search(
        "combien de jour de congé payé par mois de travail effectif",
        [result["id"]],
    )
    mapper = Mapper()
    data_to_send_to_llm = mapper.get_original_docs(rag_response, data)

    llm_processor = LLMProcessor()
    # res = llm_processor.get_answer(
    #     "Combien de jours de congé payé par mois de travail effectif ?",
    #     data_to_send_to_llm,
    # )

    # print(res)

    for token in llm_processor.get_answer_stream(
        "Combien de jours de congé payé par mois de travail effectif ?",
        data_to_send_to_llm,
    ):
        print(token, end="", flush=True)


if __name__ == "__main__":
    main()
