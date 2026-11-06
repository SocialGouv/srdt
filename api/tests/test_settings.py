"""The environment is read and validated once, by `get_settings()` at startup."""

import pytest

from srdt_analysis.core.exceptions import ConfigurationError
from srdt_analysis.core.settings import get_settings


def test_defaults():
    settings = get_settings()
    assert settings.search_engine == "opensearch"
    assert settings.search_index == "chunks"
    assert (settings.api_host, settings.api_port) == ("localhost", 8000)


@pytest.mark.parametrize("engine", ["opensearch", "elasticsearch"])
def test_engine_from_environment(monkeypatch, engine):
    monkeypatch.setenv("SEARCH_ENGINE", engine)
    assert get_settings().search_engine == engine


def test_unknown_engine_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv("SEARCH_ENGINE", "solr")
    with pytest.raises(ConfigurationError, match="SEARCH_ENGINE"):
        get_settings()


def test_index_from_environment(monkeypatch):
    monkeypatch.setenv("SEARCH_INDEX", "chunks-v2")
    assert get_settings().search_index == "chunks-v2"


def test_empty_index_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("SEARCH_INDEX", "")
    assert get_settings().search_index == "chunks"


def test_credentials_fall_back_to_the_former_name(monkeypatch):
    # the deployed sealed secrets still hold ELASTIC_API_KEY
    monkeypatch.delenv("SEARCH_CREDENTIALS")
    monkeypatch.setenv("ELASTIC_API_KEY", "dG9rZW4=")
    assert get_settings().search_credentials.get_secret_value() == "dG9rZW4="


def test_search_credentials_win_over_the_former_name(monkeypatch):
    monkeypatch.setenv("ELASTIC_API_KEY", "old:secret")
    assert get_settings().search_credentials.get_secret_value() == "user:password"


def test_secrets_are_not_printed():
    assert "password" not in repr(get_settings())


@pytest.mark.parametrize(
    "name",
    [
        "AUTH_API_KEY",
        "TIKTOKEN_TOKENIZER_MODEL",
        "ALBERT_API_KEY",
        "ALBERT_ENDPOINT",
        "ALBERT_VECTORISATION_MODEL",
        "SEARCH_HOSTNAME",
        "SEARCH_CREDENTIALS",
    ],
)
def test_missing_variable_is_a_configuration_error(monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(ConfigurationError, match=name):
        get_settings()


def test_all_the_missing_variables_are_reported_at_once(monkeypatch):
    monkeypatch.delenv("SEARCH_HOSTNAME")
    monkeypatch.delenv("ALBERT_ENDPOINT")
    with pytest.raises(ConfigurationError) as error:
        get_settings()
    assert "SEARCH_HOSTNAME" in str(error.value)
    assert "ALBERT_ENDPOINT" in str(error.value)


def test_former_hostname_name_is_ignored(monkeypatch):
    monkeypatch.delenv("SEARCH_HOSTNAME")
    monkeypatch.setenv("ELASTIC_HOSTNAME", "http://old:9200")
    with pytest.raises(ConfigurationError, match="SEARCH_HOSTNAME"):
        get_settings()
