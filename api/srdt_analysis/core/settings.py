"""Environment settings of the api, read and validated once.

`get_settings()` is called at startup (see the lifespan in api/main.py), so a missing
variable stops the api there instead of failing the first request that needs it.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from srdt_analysis.core.exceptions import ConfigurationError

SearchEngine = Literal["opensearch", "elasticsearch"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parents[2] / ".env",
        env_ignore_empty=True,
        extra="ignore",
        populate_by_name=True,
    )

    api_host: str = "localhost"
    api_port: int = 8000
    auth_api_key: SecretStr

    tiktoken_tokenizer_model: str

    albert_api_key: SecretStr
    albert_endpoint: str
    albert_vectorisation_model: str

    # OpenSearch or Elasticsearch: the same client reaches both, only the vector
    # queries differ. `search_index` is the index (or alias) ingestion writes to.
    search_engine: SearchEngine = "opensearch"
    search_index: str = "chunks"
    search_hostname: str
    # `user:password`, or the base64 token of it. ELASTIC_API_KEY is the former name,
    # still the key of the deployed sealed secrets: drop it once they are sealed again
    # as SEARCH_CREDENTIALS
    search_credentials: SecretStr = Field(
        validation_alias=AliasChoices("SEARCH_CREDENTIALS", "ELASTIC_API_KEY")
    )


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()  # pyright: ignore[reportCallIssue]
    except ValidationError as e:
        problems = ", ".join(
            f"{str(error['loc'][0]).upper()} ({error['msg'].lower()})"
            for error in e.errors()
        )
        raise ConfigurationError(f"Invalid environment: {problems}") from e
