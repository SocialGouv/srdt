from srdt_analysis.data_exploiter import (
    ArticlesCodeDuTravailExploiter,
    BaseDataExploiter,
    FichesMTExploiter,
    FichesSPExploiter,
    PageContribsExploiter,
    PageInfosExploiter,
)
from srdt_analysis.models import (
    ChunkDataList,
    ChunkDataListWithDocument,
    CollectionName,
    DocumentsList,
)


class Mapper:
    def __init__(self):
        self.source_exploiters: dict[CollectionName, BaseDataExploiter] = {
            "code_du_travail": ArticlesCodeDuTravailExploiter(),
            "page_fiche_ministere_travail": FichesMTExploiter(),
            "fiches_service_public": FichesSPExploiter(),
            "information": PageInfosExploiter(),
            "contributions": PageContribsExploiter(),
        }

    def get_exploiter(self, source: CollectionName) -> BaseDataExploiter:
        exploiter = self.source_exploiters.get(source)
        if not exploiter:
            raise ValueError(f"No exploiter found for source: {source}")
        return exploiter

    def get_original_docs(
        self,
        rag_response: ChunkDataList,
        documents_by_source: dict[CollectionName, DocumentsList],
    ) -> ChunkDataListWithDocument:
        all_documents = [doc for docs in documents_by_source.values() for doc in docs]
        doc_map = {doc.cdtn_id: doc for doc in all_documents}

        enriched_data = []
        for item in rag_response["data"]:
            cdtn_id = item["chunk"]["metadata"]["cdtn_id"]
            if cdtn_id in doc_map:
                enriched_data.append(
                    {
                        "score": item["score"],
                        "chunk": item["chunk"],
                        "document": doc_map[cdtn_id],
                        "content": self.get_exploiter(
                            doc_map[cdtn_id].source
                        ).get_content(doc_map[cdtn_id]),
                    }
                )

        enriched_data.sort(key=lambda x: x["score"], reverse=True)

        return {"object": rag_response["object"], "data": enriched_data}
