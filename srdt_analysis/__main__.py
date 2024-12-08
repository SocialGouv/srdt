from dotenv import load_dotenv

from srdt_analysis.collections import Collections
from srdt_analysis.data_exploiter import PageInfosExploiter
from srdt_analysis.database_manager import get_data
from srdt_analysis.llm_processor import LLMProcessor
from srdt_analysis.mapper import Mapper

load_dotenv()

QUESTION = "Combien de jours de congé payé par mois de travail effectif ?"
COLLECTION_ID = "40981583-0885-4e88-8e51-2d47f2d397a8"


def main():
    data = get_data(["information"])
    exploiter = PageInfosExploiter()
    result = exploiter.process_documents(data["information"], "cdtn_page_infos")
    collections = Collections()
    rag_response = collections.search(
        QUESTION,
        [result["id"]],
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
