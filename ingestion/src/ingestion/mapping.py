"""Search index definition for `ChunkDocument`, for OpenSearch or Elasticsearch.

Strict: every field is declared. The text + `.keyword` pairs reproduce what dynamic
mapping used to create, because the api queries those `.keyword` subfields.
"""

from typing import Any

from ingestion.settings import SearchEngine

TEXT_KEYWORD = {
    "type": "text",
    "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
}
KEYWORD = {"type": "keyword"}

FRENCH_ANALYSIS = {
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


def embedding_field(dim: int, engine: SearchEngine) -> dict[str, Any]:
    if engine == "elasticsearch":
        # default index options: hnsw, as the dynamic mapping used to build
        return {
            "type": "dense_vector",
            "dims": dim,
            "index": True,
            "similarity": "cosine",
        }
    # lucene engine: filtered knn, and the same score scale as cosine
    return {
        "type": "knn_vector",
        "dimension": dim,
        "method": {
            "name": "hnsw",
            "space_type": "cosinesimil",
            "engine": "lucene",
            "parameters": {"m": 16, "ef_construction": 100},
        },
    }


def mappings(dim: int, engine: SearchEngine) -> dict[str, Any]:
    return {
        "dynamic": "strict",
        "properties": {
            "id": TEXT_KEYWORD,
            "content": {"type": "text", "analyzer": "ascii_french"},
            "doc_hash": KEYWORD,
            "embed_hash": KEYWORD,
            "embedding": embedding_field(dim, engine),
            "metadata": {
                "properties": {
                    "id": TEXT_KEYWORD,
                    "source": KEYWORD,
                    "title": TEXT_KEYWORD,
                    "url": TEXT_KEYWORD,
                    "idcc": KEYWORD,
                    "idx": {"type": "long"},
                    "initial_id": TEXT_KEYWORD,
                    "articles": {
                        "properties": {"num": TEXT_KEYWORD, "url": TEXT_KEYWORD}
                    },
                    "number": TEXT_KEYWORD,
                    "decision_date": {"type": "date"},
                    "legi_links": {"type": "object", "enabled": False},
                }
            },
        },
    }


def index_settings(engine: SearchEngine) -> dict[str, Any]:
    # refresh disabled while bulk loading; restored before the alias swap
    settings: dict[str, Any] = {
        "refresh_interval": "-1",
        "analysis": FRENCH_ANALYSIS,
    }
    if engine == "opensearch":
        settings["index.knn"] = True
    return settings
