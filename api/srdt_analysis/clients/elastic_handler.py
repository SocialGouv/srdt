import os
import random
from collections import defaultdict
from timeit import default_timer as timer
from typing import List, Optional

from elasticsearch import Elasticsearch

from srdt_analysis.api.schemas import ChunkMetadata, ChunkResult
from srdt_analysis.clients.collections import AlbertCollectionHandler
from srdt_analysis.core.constants import ELASTIC_BULK_BATCH_SIZE
from srdt_analysis.core.exceptions import (
    ConfigurationError,
    ExternalServiceError,
    ServiceUnavailableError,
)
from srdt_analysis.core.logger import Logger

french_analyzer = {
    "filter": {
        "french_elision": {
            "type": "elision",
            "articles_case": True,
            "articles": [
                "l",
                "m",
                "t",
                "qu",
                "n",
                "j",
                "s",
                "d",
                "c",
                "jusqu",
                "quoiqu",
                "lorsqu",
                "puisqu",
            ],
        },
        "french_stop": {"type": "stop", "stopwords": "_french_"},
        "french_stemmer": {"type": "stemmer", "language": "light_french"},
    },
    "analyzer": {
        "ascii_french": {
            "tokenizer": "standard",
            "filter": [
                "french_elision",
                "lowercase",
                "asciifolding",
                "french_stop",
                "french_stemmer",
            ],
        }
    },
}


class ElasticIndicesHandler:
    def __init__(self):
        self.logger = Logger("Elastic")
        self.api_key = os.getenv("ELASTIC_API_KEY")
        if not self.api_key:
            raise ConfigurationError(
                "ELASTIC_API_KEY environment variable is not set",
                service="Elasticsearch",
            )

        self.base_url = os.getenv("ELASTIC_HOSTNAME")
        if not self.base_url:
            raise ConfigurationError(
                "ELASTIC_HOSTNAME environment variable is not set",
                service="Elasticsearch",
            )

        self.client = Elasticsearch(
            [self.base_url],
            basic_auth=self.api_key,
            verify_certs=False,
            request_timeout=30,
        )

        self.albert = AlbertCollectionHandler()

    def check_connection(self):
        try:
            return self.client.info()
        except Exception as e:
            raise ServiceUnavailableError(
                f"Elasticsearch unreachable: {str(e)}", service="Elasticsearch"
            ) from e

    def create_index_name(self, name):
        suff = random.randint(0, 100000)  # nosec B311
        return f"{name}-{suff}"

    def init_index(self, config):
        new_name = self.create_index_name(config["name"])
        self.client.indices.create(
            index=new_name,
            mappings=config["mappings"],
            settings=config["settings"],
        )
        return new_name

    def swap_aliases(self, index_name, alias):
        self.client.indices.update_aliases(
            actions=[
                {"remove": {"alias": index_name, "index": f"{index_name}-*"}},
                {"add": {"alias": index_name, "index": alias}},
            ]
        )

        stale_indices = [
            index
            for index in self.client.indices.get(index=f"{index_name}-*").keys()
            if index != alias
        ]
        if stale_indices:
            self.logger.info(f"Deleting {len(stale_indices)} old indices.")
            self.client.indices.delete(index=stale_indices)

    def copy_other_sources(self, index_name, alias, sources: list[str]):
        """Copy into `alias` the chunks of the current `index_name` index whose
        source is not in `sources` (reindexed by Elastic, embeddings included).
        """
        if not self.client.indices.exists_alias(name=index_name):
            self.logger.info(f"No current {index_name} index, nothing to copy.")
            return

        response = self.client.options(request_timeout=3600).reindex(
            source={
                "index": index_name,
                "query": {
                    "bool": {"must_not": [{"terms": {"metadata.source": sources}}]}
                },
            },
            dest={"index": alias},
            refresh=True,
        )
        self.logger.info(
            f"Copied {response['total']} chunks from current {index_name} index."
        )

    def add_items(self, index_name, items):
        batch_size = ELASTIC_BULK_BATCH_SIZE
        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]
            operations = []
            for item in batch:
                operations.append({"index": {"_index": index_name}})
                operations.append(item)

            self.client.bulk(index=index_name, operations=operations, refresh=True)

    def init_index_default(self, index_name):
        return self.init_index(
            {
                "name": index_name,
                "mappings": {
                    "properties": {
                        "content": {"type": "text", "analyzer": "ascii_french"},
                        "metadata.idcc": {"type": "keyword"},
                        "metadata.legi_links": {"type": "object", "enabled": False},
                    }
                },
                "settings": {"analysis": french_analyzer},
            }
        )

    def reset_index(self, index_name, items):
        alias = self.init_index(index_name)
        self.add_items(alias, items)
        self.swap_aliases(index_name, alias)

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
                size=k,
                query={
                    "bool": {
                        "must": [{"match": {"content": query}}],
                        "filter": filters,
                    }
                },
                source_includes=["content", "metadata"],
            )
            return [self.to_chunk_result(hit) for hit in response["hits"]["hits"][:k]]
        except Exception as e:
            raise ExternalServiceError(
                f"Elasticsearch error - text search : {str(e)}", service="Elasticsearch"
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
        embeddings = self.albert.embeddings([query])[0]

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
            response = self.client.search(
                index=index_name,
                knn={
                    "field": "embedding",
                    "query_vector": embeddings,
                    "num_candidates": int(k * 1.5),
                    "k": k,
                    "filter": filters,
                },
                size=k,
                source_includes=["content", "metadata"],
            )
            return [self.to_chunk_result(hit) for hit in response["hits"]["hits"]]
        except Exception as e:
            raise ExternalServiceError(
                f"Elasticsearch error - vector search : {str(e)}",
                service="Elasticsearch",
            ) from e

    def get_linked_chunk_ids(self, index_name: str, doc_ids: List[str]) -> list[str]:
        """Code du travail chunks cited (resolved legi_links) by the `doc_ids`
        documents. Links are copied on every chunk, so only the first one is read.
        """
        try:
            response = self.client.search(
                index=index_name,
                query={
                    "bool": {
                        "filter": [
                            {"terms": {"metadata.id.keyword": doc_ids}},
                            {"term": {"metadata.idx": 0}},
                        ]
                    }
                },
                size=len(doc_ids),
                source_includes=["metadata.legi_links"],
            )
        except Exception as e:
            raise ExternalServiceError(
                f"Elasticsearch query error: {str(e)}", service="Elasticsearch"
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
                query={
                    "bool": {
                        "must": list(
                            filter(
                                None,
                                [
                                    {"term": {"metadata.source": "contributions_idcc"}},
                                    {"term": {"metadata.idcc": idcc}}
                                    if idcc is not None
                                    else None,
                                ],
                            )
                        )
                    }
                },
                size=size,
                source_includes=["content", "metadata"],
            )
            return [hit["_source"] for hit in response["hits"]["hits"]]
        except Exception as e:
            raise ExternalServiceError(
                f"Elasticsearch query error: {str(e)}", service="Elasticsearch"
            ) from e

    def get_chunks(self, index_name: str, doc_ids: List[str]):
        try:
            response = self.client.search(
                index=index_name,
                query={"terms": {"metadata.id.keyword": doc_ids}},
                size=1000,
                source_includes=["content", "metadata"],
            )
            return [hit["_source"] for hit in response["hits"]["hits"]]
        except Exception as e:
            raise ExternalServiceError(
                f"Elasticsearch query error: {str(e)}", service="Elasticsearch"
            ) from e

    def get_article_node(self, index_name: str, num: str):
        try:
            response = self.client.search(
                index=index_name,
                query={"term": {"metadata.articles.num.keyword": num}},
                size=1,
                source_includes=["metadata.articles"],
            )
            return [hit["_source"] for hit in response["hits"]["hits"]]
        except Exception as e:
            raise ExternalServiceError(
                f"Elasticsearch query error: {str(e)}", service="Elasticsearch"
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
                query={"terms": {"metadata.url.keyword": urls}},
                size=0,
                aggregations={"urls": {"terms": {"field": "metadata.url.keyword"}}},
            )
            buckets = [b["key"] for b in response["aggregations"]["urls"]["buckets"]]
            return [(url, url in buckets) for url in urls]
        except Exception as e:
            raise ExternalServiceError(
                f"Elasticsearch query error: {str(e)}", service="Elasticsearch"
            ) from e
