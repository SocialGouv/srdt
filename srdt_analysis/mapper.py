from srdt_analysis.data_exploiter import (
    ArticlesCodeDuTravailExploiter,
    BaseDataExploiter,
    FichesMTExploiter,
    FichesSPExploiter,
    PageInfosExploiter,
)
from srdt_analysis.models import (
    CollectionName,
    DocumentsList,
    RAGChunkSearchResult,
    RAGChunkSearchResultEnriched,
)


class Mapper:
    def __init__(self, documents_by_source: dict[CollectionName, DocumentsList]):
        self.source_exploiters: dict[CollectionName, BaseDataExploiter] = {
            "code_du_travail": ArticlesCodeDuTravailExploiter(),
            "page_fiche_ministere_travail": FichesMTExploiter(),
            "fiches_service_public": FichesSPExploiter(),
            "information": PageInfosExploiter(),
        }
        all_documents = [doc for docs in documents_by_source.values() for doc in docs]
        self.doc_map = {doc.cdtn_id: doc for doc in all_documents}

    def get_exploiter(self, source: CollectionName) -> BaseDataExploiter:
        exploiter = self.source_exploiters.get(source)
        if not exploiter:
            raise ValueError(f"No exploiter found for source: {source}")
        return exploiter

    def get_original_docs(
        self,
        rag_response: RAGChunkSearchResult,
    ) -> RAGChunkSearchResultEnriched:
        enriched_data = []
        for item in rag_response["data"]:
            id = item["chunk"]["metadata"]["id"]
            source = item["chunk"]["metadata"]["source"]
            if id in self.doc_map:
                enriched_data.append(
                    {
                        "score": item["score"],
                        "chunk": item["chunk"],
                        "document": self.doc_map[id],
                        "content": self.get_exploiter(source).get_content(
                            self.doc_map[id]
                        ),
                    }
                )

        enriched_data.sort(key=lambda x: x["score"], reverse=True)

        return {"object": rag_response["object"], "data": enriched_data}
