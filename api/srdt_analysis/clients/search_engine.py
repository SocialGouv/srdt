"""Search engine specifics: OpenSearch or Elasticsearch, chosen by `SEARCH_ENGINE`.

Both are reached with the same client (`opensearch-py`): the REST endpoints are the
same, only the vector query bodies differ.
"""

from typing import Any

from opensearchpy import OpenSearch

from srdt_analysis.core.settings import SearchEngine

ENGINE_LABELS: dict[SearchEngine, str] = {
    "opensearch": "OpenSearch",
    "elasticsearch": "Elasticsearch",
}


def build_client(hostname: str, credentials: str) -> OpenSearch:
    """`user:password` is sent as basic auth. A value without `:` is the
    base64 `user:password` token that deployed environments hold: it is sent as is
    (`Authorization: Basic <token>`), as the Elasticsearch client used to do."""
    auth: dict[str, Any]
    if ":" in credentials:
        auth = {"http_auth": credentials}
    else:
        auth = {"headers": {"Authorization": f"Basic {credentials}"}}
    return OpenSearch(
        hosts=[hostname],
        verify_certs=False,
        ssl_show_warn=False,
        timeout=30,
        **auth,
    )


def exact_score_script(engine: SearchEngine) -> str:
    """Painless script scoring every filtered chunk, on the same scale as the knn
    score of a cosine field."""
    field = "'embedding'" if engine == "elasticsearch" else "doc['embedding']"
    return f"(cosineSimilarity(params.query_vector, {field}) + 1.0) / 2.0"


def knn_query(
    engine: SearchEngine, vector: list[float], k: int, filters: list[dict]
) -> dict[str, Any]:
    """Approximate k nearest neighbours among the chunks kept by `filters`, as the
    part of the search body that differs between the engines."""
    if engine == "elasticsearch":
        return {
            "knn": {
                "field": "embedding",
                "query_vector": vector,
                "num_candidates": int(k * 1.5),
                "k": k,
                "filter": filters,
            }
        }
    return {
        "query": {
            "knn": {
                "embedding": {
                    "vector": vector,
                    "k": k,
                    "filter": {"bool": {"filter": filters}},
                }
            }
        }
    }
