"""Search engine selection: OpenSearch or Elasticsearch, chosen by `SEARCH_ENGINE`.

Both are reached with the same client (`opensearch-py`): the REST endpoints are the
same, only the vector query bodies differ.
"""

import os
from typing import Any, Literal, Optional

from opensearchpy import OpenSearch

from srdt_analysis.core.exceptions import ConfigurationError

SearchEngine = Literal["opensearch", "elasticsearch"]

DEFAULT_SEARCH_ENGINE: SearchEngine = "opensearch"

ENGINE_LABELS: dict[SearchEngine, str] = {
    "opensearch": "OpenSearch",
    "elasticsearch": "Elasticsearch",
}

HOSTNAME_VARIABLES = ("SEARCH_HOSTNAME",)
# ELASTIC_API_KEY is the former name, still the key of the deployed sealed secrets:
# drop it once they are sealed again as SEARCH_CREDENTIALS
CREDENTIALS_VARIABLES = ("SEARCH_CREDENTIALS", "ELASTIC_API_KEY")


def get_search_engine() -> SearchEngine:
    value = os.getenv("SEARCH_ENGINE") or DEFAULT_SEARCH_ENGINE
    for engine in ENGINE_LABELS:
        if engine == value:
            return engine
    raise ConfigurationError(
        f"SEARCH_ENGINE must be one of {', '.join(ENGINE_LABELS)} (got '{value}')",
        service="Search",
    )


def _first_env(names: tuple[str, ...]) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def get_connection_settings(engine: SearchEngine) -> tuple[str, str]:
    """Hostname and credentials of the search engine, from the environment."""
    label = ENGINE_LABELS[engine]
    hostname = _first_env(HOSTNAME_VARIABLES)
    if not hostname:
        raise ConfigurationError(
            f"{' or '.join(HOSTNAME_VARIABLES)} environment variable is not set",
            service=label,
        )
    credentials = _first_env(CREDENTIALS_VARIABLES)
    if not credentials:
        raise ConfigurationError(
            f"{' or '.join(CREDENTIALS_VARIABLES)} environment variable is not set",
            service=label,
        )
    return hostname, credentials


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
