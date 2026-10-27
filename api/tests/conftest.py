import pytest

from srdt_analysis.core.settings import Settings, get_settings

# a complete, valid environment: tests change or remove the variables they exercise
ENVIRONMENT = {
    "AUTH_API_KEY": "auth-key",  # pragma: allowlist secret
    "TIKTOKEN_TOKENIZER_MODEL": "o200k_base",
    "ALBERT_API_KEY": "key",  # pragma: allowlist secret
    "ALBERT_ENDPOINT": "http://localhost:8000",
    "ALBERT_VECTORISATION_MODEL": "model",
    "SEARCH_HOSTNAME": "http://localhost:9200",
    "SEARCH_CREDENTIALS": "user:password",  # pragma: allowlist secret
}
OPTIONAL = (
    "API_HOST",
    "API_PORT",
    "SEARCH_ENGINE",
    "SEARCH_INDEX",
    "ELASTIC_API_KEY",
)


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    # the settings never read the developer's own .env
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in OPTIONAL:
        monkeypatch.delenv(name, raising=False)
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
