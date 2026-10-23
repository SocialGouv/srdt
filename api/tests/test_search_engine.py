"""The search engine is chosen by `SEARCH_ENGINE`: only the vector queries, which differ
between OpenSearch and Elasticsearch, and the way the credentials are sent change."""

import pytest

from srdt_analysis.clients.search_engine import (
    build_client,
    exact_score_script,
    get_connection_settings,
    get_search_engine,
    knn_query,
)
from srdt_analysis.core.exceptions import ConfigurationError

FILTERS = [{"terms": {"metadata.source": ["code_du_travail"]}}]
VECTOR = [0.1, 0.2, 0.3]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in (
        "SEARCH_ENGINE",
        "SEARCH_HOSTNAME",
        "SEARCH_CREDENTIALS",
        "ELASTIC_HOSTNAME",
        "ELASTIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_engine_defaults_to_opensearch():
    assert get_search_engine() == "opensearch"


@pytest.mark.parametrize("engine", ["opensearch", "elasticsearch"])
def test_engine_from_environment(monkeypatch, engine):
    monkeypatch.setenv("SEARCH_ENGINE", engine)
    assert get_search_engine() == engine


def test_unknown_engine_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv("SEARCH_ENGINE", "solr")
    with pytest.raises(ConfigurationError, match="solr"):
        get_search_engine()


def test_connection_settings_from_the_search_variables(monkeypatch):
    monkeypatch.setenv("SEARCH_HOSTNAME", "http://search:9200")
    monkeypatch.setenv("SEARCH_CREDENTIALS", "user:password")
    assert get_connection_settings("opensearch") == (
        "http://search:9200",
        "user:password",
    )


def test_credentials_fall_back_to_the_former_name(monkeypatch):
    # the deployed sealed secrets still hold ELASTIC_API_KEY
    monkeypatch.setenv("SEARCH_HOSTNAME", "http://search:9200")
    monkeypatch.setenv("ELASTIC_API_KEY", "dG9rZW4=")
    assert get_connection_settings("elasticsearch") == (
        "http://search:9200",
        "dG9rZW4=",
    )


def test_search_credentials_win_over_the_former_name(monkeypatch):
    monkeypatch.setenv("SEARCH_HOSTNAME", "http://search:9200")
    monkeypatch.setenv("SEARCH_CREDENTIALS", "new:secret")
    monkeypatch.setenv("ELASTIC_API_KEY", "old:secret")
    assert get_connection_settings("opensearch") == ("http://search:9200", "new:secret")


def test_former_hostname_name_is_ignored(monkeypatch):
    monkeypatch.setenv("ELASTIC_HOSTNAME", "http://old:9200")
    monkeypatch.setenv("SEARCH_CREDENTIALS", "user:password")
    with pytest.raises(ConfigurationError, match="SEARCH_HOSTNAME"):
        get_connection_settings("opensearch")


@pytest.mark.parametrize("missing", ["hostname", "credentials"])
def test_missing_connection_settings(monkeypatch, missing):
    if missing != "hostname":
        monkeypatch.setenv("SEARCH_HOSTNAME", "http://search:9200")
    if missing != "credentials":
        monkeypatch.setenv("SEARCH_CREDENTIALS", "user:password")
    with pytest.raises(ConfigurationError):
        get_connection_settings("opensearch")


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
