from typing import List
from elasticsearch import Elasticsearch
import random

from srdt_analysis.collections import AlbertCollectionHandler
from srdt_analysis.api.schemas import ChunkResult


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
        alias = self.init_index({"name": index_name, "mappings": {}, "settings": {}})
        self.add_items(alias, items)
        self.swap_aliases(index_name, alias)

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
        return self.find_most_similar_knn(index_name="contributions", query=prompt, k=k)
