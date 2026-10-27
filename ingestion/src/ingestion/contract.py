"""Shape of the chunks stored in the search index.

`ChunkDocument` is the published contract: `ingest schema` writes its JSON
schema to schema/chunk.v<major>.schema.json, for the api and any other reader.
Versioning: an additive change bumps the minor version, anything else the major
version (new schema file, new index, api deployed with it).
"""

import hashlib
import json
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0.0"
SCHEMA_MAJOR = SCHEMA_VERSION.split(".")[0]

# Bumped whenever the chunk text produced for unchanged inputs changes.
CHUNKER_VERSION = "1"

SourceName = Literal[
    "contributions",
    "contributions_idcc",
    "information",
    "page_fiche_ministere_travail",
    "fiches_service_public",
    "code_du_travail",
    "conventions",
    "judilibre",
]
SOURCES: tuple[SourceName, ...] = get_args(SourceName)


class Article(BaseModel):
    model_config = ConfigDict(extra="forbid")

    num: str = Field(description="Article number, e.g. L1242-3")
    url: str = Field(description="Legifrance url of the article")


class LegiLink(BaseModel):
    """Legifrance link to a code found in a CDTN document, resolved against the
    code du travail."""

    model_config = ConfigDict(extra="forbid")

    legi_id: str = Field(description="LEGIARTI/LEGISCTA id parsed from the url")
    url: str
    label: str | None
    origin: str = Field(description="Where the link was found in the document")
    kind: Literal["article", "section"] | None = Field(
        description="None when the id is not in the code du travail"
    )
    cid: str | None
    num: str | None
    chunk_id: str | None = Field(
        description="metadata.id of the code du travail chunks holding the target"
    )
    canonical_url: str | None


class ChunkMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description="Document id, shared by all the chunks of a document "
        "(cdtn_id, LEGI section cid, KALI article id, Judilibre decision-summary id)"
    )
    source: SourceName
    title: str
    url: str
    idcc: str | None = Field(description="Collective agreement number, unpadded")
    idx: int = Field(ge=0, description="Position of the chunk in its document")
    initial_id: str | None
    articles: list[Article] | None = Field(
        description="Code du travail articles of the chunk (code_du_travail only)"
    )
    # judilibre only
    number: str | None = None
    decision_date: str | None = None
    # CDTN sources only
    legi_links: list[LegiLink] | None = None


class Chunk(BaseModel):
    """A chunk before embedding."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Same as metadata.id (kept for compatibility)")
    content: str = Field(description="Chunk text, as embedded and returned")
    metadata: ChunkMetadata

    @property
    def chunk_id(self) -> str:
        return chunk_id(self.metadata)

    def stored_fields(self) -> dict[str, Any]:
        # unset optional metadata (number, legi_links...) stays absent, as before
        return self.model_dump(mode="json", exclude_unset=True)

    def compute_doc_hash(self) -> str:
        canonical = json.dumps(
            self.stored_fields(),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return sha256(canonical)

    def to_document(self, model_id: str, embedding: list[float]) -> "ChunkDocument":
        return ChunkDocument.model_validate(
            {
                **self.stored_fields(),
                "doc_hash": self.compute_doc_hash(),
                "embed_hash": embed_hash(model_id, self.content),
                "embedding": embedding,
            }
        )


class ChunkDocument(Chunk):
    """A chunk as stored in the index. Its `_id` in the index is
    `{metadata.source}:{metadata.idcc or "-"}:{metadata.id}:{metadata.idx}`."""

    doc_hash: str = Field(
        description="sha256 of the canonical JSON of id, content and metadata"
    )
    embed_hash: str = Field(
        description="sha256 of the embedding model id and the embedded text"
    )
    embedding: list[float] = Field(
        description="Dense vector; model and dimension are in the index _meta"
    )


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_id(metadata: ChunkMetadata) -> str:
    # idcc is part of the id: an attached text shared by several collective
    # agreements yields the same KALI article under each of them
    return f"{metadata.source}:{metadata.idcc or '-'}:{metadata.id}:{metadata.idx}"


def embed_hash(model_id: str, text: str) -> str:
    return sha256(f"{model_id}\n{text}")


def json_schema() -> dict[str, Any]:
    schema = ChunkDocument.model_json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **schema,
        "title": "Search chunk",
        "x-schema-version": SCHEMA_VERSION,
    }
