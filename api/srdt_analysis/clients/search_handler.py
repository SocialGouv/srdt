from collections import defaultdict
from timeit import default_timer as timer
from typing import List, Optional, cast

from srdt_analysis.api.schemas import ChunkMetadata, ChunkResult
from srdt_analysis.clients.albert import AlbertClient
from srdt_analysis.clients.search_engine import (
    ENGINE_LABELS,
    SearchEngine,
    build_client,
    exact_score_script,
    get_connection_settings,
    get_search_engine,
    knn_query,
)
from srdt_analysis.core.constants import EXACT_KNN_MAX_CHUNKS
from srdt_analysis.core.exceptions import (
    ExternalServiceError,
    ServiceUnavailableError,
)
from srdt_analysis.core.logger import Logger


class SearchIndexHandler:
    def __init__(self):
        self.logger = Logger("Search")
        self.engine: SearchEngine = get_search_engine()
        self.label = ENGINE_LABELS[self.engine]
        self.client = build_client(*get_connection_settings(self.engine))
        self.albert = AlbertClient()

    def check_connection(self):
        try:
            return self.client.info()
        except Exception as e:
            raise ServiceUnavailableError(
                f"{self.label} unreachable: {str(e)}", service=self.label
            ) from e

    def to_chunk_result(self, r) -> ChunkResult:
        source = r["_source"]
        metadataDict = source["metadata"]
        metadata = ChunkMetadata(
            id=metadataDict["id"],
            source=metadataDict["source"],
            idcc=metadataDict["idcc"],
            title=metadataDict["title"],
            url=metadataDict["url"],
            number=metadataDict.get("number"),
            decision_date=metadataDict.get("decision_date"),
        )
        return ChunkResult(
            id_chunk=r["_id"],
            score=r["_score"],
            metadata=metadata,
            content=source["content"],
        )

    def find_most_similar_text(
        self,
        index_name,
        query,
        k,
        sources: list[str],
        idcc: Optional[str],
        ids: Optional[list[str]] = None,
    ) -> list[ChunkResult]:
        filters: list[dict] = [{"terms": {"metadata.source": sources}}]
        if idcc is not None:
            filters.append({"term": {"metadata.idcc": idcc}})
        if ids is not None:
            filters.append({"terms": {"metadata.id.keyword": ids}})

        try:
            response = self.client.search(
                index=index_name,
                body={
                    "size": k,
                    "query": {
                        "bool": {
                            "must": [{"match": {"content": query}}],
                            "filter": filters,
                        }
                    },
                    "_source": {"includes": ["content", "metadata"]},
                },
            )
            return [self.to_chunk_result(hit) for hit in response["hits"]["hits"][:k]]
        except Exception as e:
            raise ExternalServiceError(
                f"{self.label} error - text search : {str(e)}", service=self.label
            ) from e

    def find_most_similar_knn(
        self,
        index_name,
        query,
        k,
        sources: list[str],
        idcc: Optional[str],
        ids: Optional[list[str]] = None,
    ):
        # `AlbertClient.embeddings` is annotated `list[float]`, it returns one vector
        # per input
        embeddings = cast(list[float], self.albert.embeddings([query])[0])

        # pre-filter: the k nearest neighbours are searched among the filtered chunks
        filters: list[dict] = [{"terms": {"metadata.source": sources}}]
        if idcc is not None:
            # chunks of the requested idcc or without idcc
            filters.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"metadata.idcc": idcc}},
                            {
                                "bool": {
                                    "must_not": {"exists": {"field": "metadata.idcc"}}
                                }
                            },
                        ]
                    }
                }
            )
        if ids is not None:
            filters.append({"terms": {"metadata.id.keyword": ids}})

        try:
            filtered = self.client.count(
                index=index_name, body={"query": {"bool": {"filter": filters}}}
            )["count"]
            if filtered <= EXACT_KNN_MAX_CHUNKS:
                body = {
                    "query": {
                        "script_score": {
                            "query": {
                                "bool": {
                                    "filter": [
                                        *filters,
                                        {"exists": {"field": "embedding"}},
                                    ]
                                }
                            },
                            "script": {
                                "source": exact_score_script(self.engine),
                                "params": {"query_vector": embeddings},
                            },
                        }
                    }
                }
            else:
                body = knn_query(self.engine, embeddings, k, filters)
            response = self.client.search(
                index=index_name,
                body={
                    **body,
                    "size": k,
                    "_source": {"includes": ["content", "metadata"]},
                },
            )
            return [self.to_chunk_result(hit) for hit in response["hits"]["hits"]]
        except Exception as e:
            raise ExternalServiceError(
                f"{self.label} error - vector search : {str(e)}",
                service=self.label,
            ) from e

    def get_linked_chunk_ids(self, index_name: str, doc_ids: List[str]) -> list[str]:
        """Code du travail chunks cited (resolved legi_links) by the `doc_ids`
        documents. Links are copied on every chunk, so only the first one is read.
        """
        try:
            response = self.client.search(
                index=index_name,
                body={
                    "query": {
                        "bool": {
                            "filter": [
                                {"terms": {"metadata.id.keyword": doc_ids}},
                                {"term": {"metadata.idx": 0}},
                            ]
                        }
                    },
                    "size": len(doc_ids),
                    "_source": {"includes": ["metadata.legi_links"]},
                },
            )
        except Exception as e:
            raise ExternalServiceError(
                f"{self.label} query error: {str(e)}", service=self.label
            ) from e

        chunk_ids: list[str] = []
        for hit in response["hits"]["hits"]:
            for link in hit["_source"].get("metadata", {}).get("legi_links") or []:
                chunk_id = link.get("chunk_id")
                if chunk_id and chunk_id not in chunk_ids:
                    chunk_ids.append(chunk_id)
        return chunk_ids

    def get_idcc_contributions(self, index_name: str, idcc: str, size: int):
        try:
            response = self.client.search(
                index=index_name,
                body={
                    "query": {
                        "bool": {
                            "must": list(
                                filter(
                                    None,
                                    [
                                        {
                                            "term": {
                                                "metadata.source": "contributions_idcc"
                                            }
                                        },
                                        {"term": {"metadata.idcc": idcc}}
                                        if idcc is not None
                                        else None,
                                    ],
                                )
                            )
                        }
                    },
                    "size": size,
                    "_source": {"includes": ["content", "metadata"]},
                },
            )
            return [hit["_source"] for hit in response["hits"]["hits"]]
        except Exception as e:
            raise ExternalServiceError(
                f"{self.label} query error: {str(e)}", service=self.label
            ) from e

    def get_chunks(self, index_name: str, doc_ids: List[str]):
        try:
            response = self.client.search(
                index=index_name,
                body={
                    "query": {"terms": {"metadata.id.keyword": doc_ids}},
                    "size": 1000,
                    "_source": {"includes": ["content", "metadata"]},
                },
            )
            return [hit["_source"] for hit in response["hits"]["hits"]]
        except Exception as e:
            raise ExternalServiceError(
                f"{self.label} query error: {str(e)}", service=self.label
            ) from e

    def get_article_node(self, index_name: str, num: str):
        try:
            response = self.client.search(
                index=index_name,
                body={
                    "query": {"term": {"metadata.articles.num.keyword": num}},
                    "size": 1,
                    "_source": {"includes": ["metadata.articles"]},
                },
            )
            return [hit["_source"] for hit in response["hits"]["hits"]]
        except Exception as e:
            raise ExternalServiceError(
                f"{self.label} query error: {str(e)}", service=self.label
            ) from e

    def search(
        self,
        index_name: str,
        prompt: str,
        k: int,
        hybrid: bool,
        sources: list[str],
        idcc: Optional[str],
        ids: Optional[list[str]] = None,
    ) -> List[ChunkResult]:
        k_min = 64 if k < 64 else k

        start = timer()

        knn_res = self.find_most_similar_knn(
            query=prompt,
            index_name=index_name,
            k=k_min,
            sources=sources,
            idcc=idcc,
            ids=ids,
        )

        knn_time = timer() - start
        self.logger.debug(f"Elapsed KNN {knn_time}s")

        if not hybrid:
            return knn_res[:k]

        start = timer()

        text_res = self.find_most_similar_text(
            query=prompt,
            index_name=index_name,
            k=k_min,
            sources=sources,
            idcc=idcc,
            ids=ids,
        )

        text_time = timer() - start
        self.logger.debug(f"Elapsed Text {text_time}s")

        if len(text_res) == 0:
            return knn_res[:k]

        start = timer()

        res_dict = {r.id_chunk: r for r in knn_res + text_res}

        # dictionary to store RRF mapping
        rrf_map = defaultdict(float)

        # calculate RRF score for each result in each list
        for rank_list in [r.id_chunk for r in knn_res], [r.id_chunk for r in text_res]:
            for rank, item in enumerate(rank_list, 1):
                # 60 : constant used in rrf
                rrf_map[item] += 1 / (rank + 60)

        # sort items based on their RRF scores in descending order
        sorted_results = sorted(rrf_map.items(), key=lambda x: x[1], reverse=True)

        # replace score with rff score
        def update_score(elem, rff_score):
            elem.score = rff_score
            return elem

        return [update_score(res_dict[id], score) for [id, score] in sorted_results[:k]]

    def check_urls(self, index_name: str, urls: list[str]) -> list[tuple[str, bool]]:
        try:
            response = self.client.search(
                index=index_name,
                body={
                    "query": {"terms": {"metadata.url.keyword": urls}},
                    "aggs": {"urls": {"terms": {"field": "metadata.url.keyword"}}},
                    "size": 0,
                },
            )
            buckets = [b["key"] for b in response["aggregations"]["urls"]["buckets"]]
            return [(url, url in buckets) for url in urls]
        except Exception as e:
            raise ExternalServiceError(
                f"{self.label} query error: {str(e)}", service=self.label
            ) from e
