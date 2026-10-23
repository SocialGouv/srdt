"""Environment settings (secrets, endpoints). What to ingest lives in config.py."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

SearchEngine = Literal["opensearch", "elasticsearch"]


class MissingSetting(RuntimeError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    # Search index, same variables as the api. The credentials are `user:password`, or
    # the base64 token of it. ELASTIC_API_KEY is the former name, still the key of the
    # deployed sealed secrets.
    search_engine: SearchEngine = "opensearch"
    search_hostname: str | None = None
    search_credentials: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("SEARCH_CREDENTIALS", "ELASTIC_API_KEY"),
    )

    # Albert embeddings
    albert_endpoint: str | None = None
    albert_api_key: SecretStr | None = None
    albert_vectorisation_model: str | None = None

    # CDTN database
    postgres_user: str | None = None
    postgres_password: SecretStr | None = None
    postgres_database_name: str | None = None
    postgres_database_url: str | None = None

    # PISTE Judilibre API (fetch only)
    judilibre_api_key: SecretStr | None = None

    # Raw source snapshots
    snapshot_store: Literal["s3", "local"] = "s3"
    snapshot_local_dir: Path = Path("snapshots")
    snapshot_cache_dir: Path = Path.home() / ".cache" / "ingestion"
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_bucket: str | None = None
    s3_prefix: str = "raw/"
    aws_access_key_id: str | None = None
    aws_secret_access_key: SecretStr | None = None

    def require(self, *names: str) -> None:
        missing = [n.upper() for n in names if not getattr(self, n)]
        if missing:
            raise MissingSetting(f"Missing environment variables: {', '.join(missing)}")


def secret(value: SecretStr | None) -> str:
    return value.get_secret_value() if value else ""
