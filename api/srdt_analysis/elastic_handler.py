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
        self.client = Elasticsearch("http://localhost:9200")
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
            # Transforming the title into an embedding using the model
            # book["title_vector"] = model.encode(book["title"]).tolist()
            operations.append(item)

        # print(operations)
        # print(index_name)
        self.client.bulk(index=index_name, operations=operations, refresh=True)

    def reset_index(self, index_name, items):
        alias = self.init_index(
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
        self.add_items(alias, items)
        self.swap_aliases(index_name, alias)

    def find_most_similar_text(self, index_name, query, k):
        response = self.client.search(
            index=index_name,
            size=k,
            query={"match": {"content": query}},
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

    def find_most_similar_knn(self, index_name, query, k):
        response = self.client.search(
            index=index_name,
            knn={
                "field": "embedding",
                "query_vector": self.albert.embeddings([query])[0],
                "num_candidates": k * 5,
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

    def search(self, prompt: str, k: int, hybrid: bool) -> List[ChunkResult]:
        k_min = 64 if k < 64 else k
        knn_res = self.find_most_similar_knn(
            query=prompt, index_name="contributions", k=k_min
        )

        if not hybrid:
            return knn_res[:k]

        text_res = self.find_most_similar_text(
            query=prompt, index_name="contributions", k=k_min
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

        print(sorted_results[:5])

        return [res_dict[id] for [id, _] in sorted_results[:k]]

        # TODO add rff score alongside orignal scores
        # return [[res_dict[id], score] for [id, score] in sorted_results[:k]]

        # return self.find_most_similar_knn(index_name="contributions", query=prompt, k=k)
        return self.find_most_similar_text(
            index_name="contributions", query=prompt, k=k
        )
