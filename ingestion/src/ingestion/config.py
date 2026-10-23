"""What to ingest: the include list, snapshot pins, embedding and index settings
(one TOML file per environment in config/)."""

import tomllib
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ingestion.contract import SourceName

Dataset = Literal["legi", "kali", "judilibre"]
DATASETS: tuple[Dataset, ...] = get_args(Dataset)

# Snapshots each source reads. The CDTN sources need LEGI to resolve their links
# to the code du travail.
SOURCE_DATASETS: dict[SourceName, tuple[Dataset, ...]] = {
    "contributions": ("legi",),
    "contributions_idcc": ("legi",),
    "information": ("legi",),
    "page_fiche_ministere_travail": ("legi",),
    "fiches_service_public": ("legi",),
    "code_du_travail": ("legi",),
    "conventions": ("kali",),
    "judilibre": ("judilibre",),
}


class EmbeddingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # canonical id written to the index _meta and hashed into embed_hash; the
    # Albert model name (ALBERT_VECTORISATION_MODEL) may differ per environment
    model_id: str
    dim: int = 1024
    batch_size: int = 64


class IndexConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str = "chunks"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include: list[SourceName] = Field(min_length=1)
    # "latest" or a snapshot id
    snapshots: dict[Dataset, str] = Field(
        default_factory=lambda: dict.fromkeys(DATASETS, "latest")
    )
    embedding: EmbeddingConfig
    index: IndexConfig = Field(default_factory=IndexConfig)

    @field_validator("include")
    @classmethod
    def no_duplicates(cls, include: list[SourceName]) -> list[SourceName]:
        if len(set(include)) != len(include):
            raise ValueError("duplicate sources in include")
        return include

    def snapshot_ref(self, dataset: Dataset) -> str:
        return self.snapshots.get(dataset, "latest")


def load_config(path: Path) -> Config:
    with open(path, "rb") as f:
        return Config.model_validate(tomllib.load(f))
