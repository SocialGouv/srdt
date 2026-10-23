"""The index is built for the engine chosen by `SEARCH_ENGINE`: only the vector field,
the knn setting and the way the credentials are sent change."""

import pytest
from pydantic import ValidationError

from ingestion.index_writer import SearchIndexWriter, build_client
from ingestion.mapping import embedding_field, index_settings, mappings
from ingestion.settings import MissingSetting, Settings

NAMES = (
    "SEARCH_ENGINE",
    "SEARCH_HOSTNAME",
    "SEARCH_CREDENTIALS",
    "ELASTIC_HOSTNAME",
    "ELASTIC_API_KEY",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def make_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_engine_defaults_to_opensearch():
    assert make_settings().search_engine == "opensearch"


def test_engine_from_environment(monkeypatch):
    monkeypatch.setenv("SEARCH_ENGINE", "elasticsearch")
    assert make_settings().search_engine == "elasticsearch"


def test_unknown_engine_is_refused(monkeypatch):
    monkeypatch.setenv("SEARCH_ENGINE", "solr")
    with pytest.raises(ValidationError):
        make_settings()


def test_connection_settings_from_the_search_variables(monkeypatch):
    monkeypatch.setenv("SEARCH_HOSTNAME", "http://search:9200")
    monkeypatch.setenv("SEARCH_CREDENTIALS", "user:password")
    settings = make_settings()
    assert settings.search_hostname == "http://search:9200"
    assert settings.search_credentials
    assert settings.search_credentials.get_secret_value() == "user:password"


def test_credentials_fall_back_to_the_former_name(monkeypatch):
    # the deployed sealed secrets still hold ELASTIC_API_KEY
    monkeypatch.setenv("ELASTIC_API_KEY", "dG9rZW4=")
    settings = make_settings()
    assert settings.search_credentials
    assert settings.search_credentials.get_secret_value() == "dG9rZW4="


def test_search_credentials_win_over_the_former_name(monkeypatch):
    monkeypatch.setenv("SEARCH_CREDENTIALS", "new:secret")
    monkeypatch.setenv("ELASTIC_API_KEY", "old:secret")
    settings = make_settings()
    assert settings.search_credentials
    assert settings.search_credentials.get_secret_value() == "new:secret"


def test_former_hostname_name_is_ignored(monkeypatch):
    monkeypatch.setenv("ELASTIC_HOSTNAME", "http://old:9200")
    assert make_settings().search_hostname is None


def test_missing_connection_settings_name_the_new_variables():
    with pytest.raises(MissingSetting, match="SEARCH_HOSTNAME, SEARCH_CREDENTIALS"):
        SearchIndexWriter(make_settings())


def test_embedding_field_per_engine():
    assert embedding_field(1024, "opensearch") == {
        "type": "knn_vector",
        "dimension": 1024,
        "method": {
            "name": "hnsw",
            "space_type": "cosinesimil",
            "engine": "lucene",
            "parameters": {"m": 16, "ef_construction": 100},
        },
    }
    assert embedding_field(1024, "elasticsearch") == {
        "type": "dense_vector",
        "dims": 1024,
        "index": True,
        "similarity": "cosine",
    }


def test_only_the_embedding_field_differs_between_engines():
    opensearch = mappings(3, "opensearch")
    elasticsearch = mappings(3, "elasticsearch")
    for mapping in (opensearch, elasticsearch):
        mapping["properties"].pop("embedding")
    assert opensearch == elasticsearch


def test_knn_setting_is_opensearch_only():
    assert index_settings("opensearch")["index.knn"] is True
    assert "index.knn" not in index_settings("elasticsearch")
    # the rest is shared
    shared = {k: v for k, v in index_settings("opensearch").items() if k != "index.knn"}
    assert shared == index_settings("elasticsearch")


def authorization_header(client) -> str | None:
    connection = client.transport.get_connection()
    headers = {name.lower(): value for name, value in connection.headers.items()}
    return headers.get("authorization")


def test_user_password_is_sent_as_basic_auth():
    header = authorization_header(build_client("http://search:9200", "user:password"))
    assert header == "Basic dXNlcjpwYXNzd29yZA=="  # base64 of `user:password`


def test_token_without_colon_is_sent_as_is():
    header = authorization_header(
        build_client("http://search:9200", "dXNlcjpwYXNzd29yZA==")
    )
    assert header == "Basic dXNlcjpwYXNzd29yZA=="
