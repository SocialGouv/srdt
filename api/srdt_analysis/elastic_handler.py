import os
from typing import List
from elasticsearch import Elasticsearch
import random

from ranx import Run, fuse

from srdt_analysis.collections import AlbertCollectionHandler
from srdt_analysis.api.schemas import ChunkResult

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
                "s",
                "j",
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
        self.client = Elasticsearch(
            [os.getenv("ELASTIC_HOSTNAME")],
            basic_auth=os.getenv("ELASTIC_API_KEY"),
            verify_certs=False,
            request_timeout=30,
        )

        self.albert = AlbertCollectionHandler()

    def create_index_name(self, name):
        suff = random.randint(0, 100000)
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

    def add_items(self, index_name, items):
        operations = []
        for item in items:
            operations.append({"index": {"_index": index_name}})
            operations.append(item)

        self.client.bulk(index=index_name, operations=operations, refresh=True)

    def init_index_default(self, index_name):
        return self.init_index(
            {
                "name": index_name,
                "mappings": {
                    "properties": {
                        "content": {"type": "text", "analyzer": "ascii_french"}
                    }
                },
                "settings": {"analysis": french_analyzer},
            }
        )

    def reset_index(self, index_name, items):
        alias = self.init_index(index_name)
        self.add_items(alias, items)
        self.swap_aliases(index_name, alias)

    def find_most_similar_text(self, index_name, query, k, sources: list[str]):

        response = self.client.search(
            index=index_name,
            size=k,
            query={
                "bool": {
                    "must": [{"match": {"content": query}}],
                    "filter": [{"terms": {"metadata.source": sources}}],
                }
            },
            source=["content", "metadata"],
        )
        return [
            {
                **{
                    "id": r["_id"],
                    "score": r["_score"],
                },
                **r["_source"],
            }
            for r in response["hits"]["hits"][:k]
        ]

    def find_most_similar_knn(self, index_name, query, k, sources: list[str]):

        response = self.client.search(
            query={"terms": {"metadata.source": sources}},
            index=index_name,
            knn={
                "field": "embedding",
                "query_vector": self.albert.embeddings([query])[0],
                "num_candidates": k * 5,
                "k": k,
            },
            size=k,
        )

        return [
            {
                **{
                    "id": r["_id"],
                    "score": r["_score"],
                },
                **r["_source"],
            }
            for r in response["hits"]["hits"][:k]
        ]

    def get_idcc(self, idcc: str):
        response = self.client.search(
            index="chunks",
            query={"term": {"metadata.idcc.keyword": idcc}},
            size=1000,
            source=["content", "metadata"],
        )
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def get_chunks(self, doc_ids: List[str]):
        response = self.client.search(
            index="chunks",
            query={"terms": {"metadata.id.keyword": doc_ids}},
            size=1000,
            source=["content", "metadata"],
        )
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def search(
        self, index_name: str, prompt: str, k: int, hybrid: bool, sources: list[str]
    ) -> List[ChunkResult]:
        k_min = 64 if k < 64 else k
        knn_res = self.find_most_similar_knn(
            query=prompt, index_name=index_name, k=k_min, sources=sources
        )

        if not hybrid:
            return knn_res[:k]

        text_res = self.find_most_similar_text(
            query=prompt, index_name=index_name, k=k_min, sources=sources
        )

        if len(text_res) == 0:
            return []

        query_id = "q"

        knn_run_dict = {query_id: {r["id"]: r["score"] for r in knn_res}}
        text_run_dict = {query_id: {r["id"]: r["score"] for r in text_res}}

        knn_run = Run.from_dict(knn_run_dict, name="knn")
        text_run = Run.from_dict(text_run_dict, name="tex")

        res_dict = {r["id"]: r for r in knn_res + text_res}

        combined_run = fuse(runs=[knn_run, text_run], method="rrf")
        sorted_results = sorted(
            combined_run[query_id].items(), key=lambda item: item[1], reverse=True
        )

        # add replace score with rff score
        def update_score(elem, rff_score):
            elem["score"] = rff_score
            return elem

        return [update_score(res_dict[id], score) for [id, score] in sorted_results[:k]]
