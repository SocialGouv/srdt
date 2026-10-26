"""The search engine is chosen by `SEARCH_ENGINE`: only the vector queries, which differ
between OpenSearch and Elasticsearch, and the way the credentials are sent change."""

from srdt_analysis.clients.search_engine import (
    build_client,
    exact_score_script,
    knn_query,
)

FILTERS = [{"terms": {"metadata.source": ["code_du_travail"]}}]
VECTOR = [0.1, 0.2, 0.3]


def authorization_header(client) -> str | None:
    connection = client.transport.get_connection()
    headers = {name.lower(): value for name, value in connection.headers.items()}
    return headers.get("authorization")


def test_user_password_is_sent_as_basic_auth():
    header = authorization_header(build_client("http://search:9200", "user:password"))
    # base64 of `user:password`
    assert header == "Basic dXNlcjpwYXNzd29yZA=="


def test_token_without_colon_is_sent_as_is():
    # deployed environments hold the base64 `user:password` token
    header = authorization_header(
        build_client("http://search:9200", "dXNlcjpwYXNzd29yZA==")
    )
    assert header == "Basic dXNlcjpwYXNzd29yZA=="


def test_exact_score_script_per_engine():
    assert "doc['embedding']" in exact_score_script("opensearch")
    assert "'embedding')" in exact_score_script("elasticsearch")
    assert "doc[" not in exact_score_script("elasticsearch")
    # both keep the 0..1 scale of the knn score of a cosine field
    for engine in ("opensearch", "elasticsearch"):
        assert "+ 1.0) / 2.0" in exact_score_script(engine)


def test_opensearch_knn_query():
    assert knn_query("opensearch", VECTOR, 64, FILTERS) == {
        "query": {
            "knn": {
                "embedding": {
                    "vector": VECTOR,
                    "k": 64,
                    "filter": {"bool": {"filter": FILTERS}},
                }
            }
        }
    }


def test_elasticsearch_knn_query():
    assert knn_query("elasticsearch", VECTOR, 64, FILTERS) == {
        "knn": {
            "field": "embedding",
            "query_vector": VECTOR,
            "num_candidates": 96,
            "k": 64,
            "filter": FILTERS,
        }
    }
