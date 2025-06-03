from srdt_analysis.data_exploiter import (
    ArticlesCodeDuTravailExploiter,
    BaseDataExploiter,
    FichesMTExploiter,
    FichesSPExploiter,
    PageInfosExploiter,
    PagesContributionsExploiter,
)
from srdt_analysis.models import (
    CollectionName,
    DocumentsList,
    EnrichedRankedChunk,
    RankedChunk,
)


class Mapper:
    def __init__(self, documents_by_source: dict[CollectionName, DocumentsList]):
        self.source_exploiters: dict[CollectionName, BaseDataExploiter] = {
            "code_du_travail": ArticlesCodeDuTravailExploiter(),
            "page_fiche_ministere_travail": FichesMTExploiter(),
            "fiches_service_public": FichesSPExploiter(),
            "information": PageInfosExploiter(),
            "contributions": PagesContributionsExploiter(),
            "contributions_idcc": PagesContributionsExploiter(),
        }
        all_documents = [doc for docs in documents_by_source.values() for doc in docs]
        self.doc_map = {doc.cdtn_id: doc for doc in all_documents}

    def _get_exploiter(self, source: CollectionName) -> BaseDataExploiter:
        exploiter = self.source_exploiters.get(source)
        if not exploiter:
            raise ValueError(f"No exploiter found for source: {source}")
        return exploiter

    def enrich_chunks(
        self,
        chunks: list[RankedChunk],
    ) -> list[EnrichedRankedChunk]:
        enriched_chunks = []
        for scored_chunk in chunks:
            id = scored_chunk["chunk"]["metadata"]["id"]
            source = scored_chunk["chunk"]["metadata"]["source"]
            if id in self.doc_map:
                enriched_chunks.append(
                    {
                        "score": scored_chunk["score"],
                        "chunk": scored_chunk["chunk"],
                        "document": self.doc_map[id],
                        "content": self._get_exploiter(source).get_content(
                            self.doc_map[id]
                        ),
                    }
                )

        enriched_chunks.sort(key=lambda x: x["score"], reverse=True)

        return enriched_chunks
