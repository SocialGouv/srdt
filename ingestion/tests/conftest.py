import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from ingestion.config import Config, EmbeddingConfig
from ingestion.contract import SOURCES, ChunkDocument, SourceName
from ingestion.pipeline import Inputs
from ingestion.settings import Settings
from ingestion.snapshots.store import LocalStore
from ingestion.sources.postgres import Document

FIXTURES = Path(__file__).parent / "fixtures"
LEGI_URL = "https://www.legifrance.gouv.fr/codes"


def _document(source: SourceName, cdtn_id: str, title: str, **fields: Any) -> Document:
    return Document(
        cdtn_id=cdtn_id,
        initial_id=f"initial-{cdtn_id}",
        title=title,
        source=source,
        slug=title.lower().replace(" ", "-"),
        text=fields.pop("text", ""),
        document=fields.pop("document"),
        updated_at=datetime(2026, 1, 1),
        idcc=fields.pop("idcc", None),
    )


def cdtn_documents() -> dict[SourceName, list[Document]]:
    """One CDTN document per Postgres source, with Legifrance links to the LEGI
    fixture (current article id, old version id, section) and outside of it."""
    sp_raw = {
        "name": "Publication",
        "children": [
            {
                "name": "Reference",
                "attributes": {"URL": f"{LEGI_URL}/article_lc/LEGIARTI000000000010"},
                "children": [
                    {"name": "Titre", "children": [{"type": "text", "text": "L1111-1"}]}
                ],
            }
        ],
    }
    return {
        "contributions": [
            _document(
                "contributions",
                "c0001",
                "La periode d'essai",
                idcc="0000",
                document={
                    "idcc": "0000",
                    "content": "<h2>Durée</h2><p>Voir l'<a href='"
                    f"{LEGI_URL}/article_lc/LEGIARTI000000000012'>article L1111-1"
                    "</a>.</p>",
                    "references": [
                        {
                            "url": f"{LEGI_URL}/id/LEGIARTI000000000011",
                            "title": "L1111-1",
                        }
                    ],
                },
            )
        ],
        "contributions_idcc": [
            _document(
                "contributions_idcc",
                "c1486",
                "La periode d'essai 1486",
                idcc="1486",
                document={
                    "idcc": "1486",
                    "content": "<p>La durée est de <strong>deux mois</strong>.</p>",
                },
            )
        ],
        "information": [
            _document(
                "information",
                "i0001",
                "Effectifs",
                document={
                    "contents": [
                        {
                            "blocks": [
                                {
                                    "type": "markdown",
                                    "markdown": "# Effectifs\n\nCalcul.",
                                }
                            ],
                            "references": [
                                {
                                    "links": [
                                        {
                                            "url": f"{LEGI_URL}/section_lc/"
                                            "LEGITEXT000006072050/LEGISCTA000000000002",
                                            "title": "Chapitre",
                                        }
                                    ]
                                }
                            ],
                        }
                    ]
                },
            )
        ],
        "page_fiche_ministere_travail": [
            _document(
                "page_fiche_ministere_travail",
                "f0001",
                "Le contrat de travail",
                document={
                    "intro": "",
                    "sections": [
                        {
                            "html": "<h2>Définition</h2><p>Le contrat est écrit.</p>",
                            "references": [
                                {
                                    "url": f"{LEGI_URL}/article_lc/"
                                    "LEGIARTI000099999999",
                                    "title": "Hors du code",
                                }
                            ],
                        }
                    ],
                },
            )
        ],
        "fiches_service_public": [
            _document(
                "fiches_service_public",
                "F1234",
                "Salarie du prive",
                text="Le salarié du privé bénéficie de congés payés.",
                document={"raw": json.dumps(sp_raw)},
            )
        ],
    }


def make_store(root: Path) -> LocalStore:
    store = LocalStore(root)
    store.put_snapshot(
        "legi",
        "2.575.0",
        {"LEGITEXT000006072050.json": FIXTURES / "LEGITEXT000006072050.json"},
        {"package": "@socialgouv/legi-data"},
    )
    store.put_snapshot(
        "kali",
        "3.514.0",
        {p.name: p for p in FIXTURES.glob("KALICONT*.json")},
        {"package": "@socialgouv/kali-data"},
    )
    store.put_snapshot(
        "judilibre", "20261023", {"2024.json": FIXTURES / "2024.json"}, {}
    )
    return store


def make_config(include: Sequence[SourceName] = SOURCES, **embedding: Any) -> Config:
    return Config(
        include=list(include),
        embedding=EmbeddingConfig(**{"model_id": "test-model", "dim": 3, **embedding}),
    )


@pytest.fixture
def store(tmp_path: Path) -> LocalStore:
    return make_store(tmp_path / "snapshots")


@pytest.fixture
def config() -> Config:
    return make_config()


def make_inputs(store: LocalStore, config: Config) -> Inputs:
    return Inputs(
        store=store,
        config=config,
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        postgres_loader=lambda _settings, sources: {
            s: d for s, d in cdtn_documents().items() if s in sources
        },
    )


@pytest.fixture
def inputs(store: LocalStore, config: Config) -> Inputs:
    return make_inputs(store, config)


class FakeEmbedder:
    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(t)), 0.0, 1.0] for t in texts]


class FakeWriter:
    def __init__(self, current: dict[str, Any] | None = None, exists: bool = False):
        self.current = current
        self.exists = exists
        self.meta: dict[str, Any] | None = None
        self.copied_excluding: list[str] | None = None
        self.documents: list[ChunkDocument] = []
        self.published: tuple[str, str] | None = None

    def current_meta(self, alias: str) -> dict[str, Any] | None:
        return self.current

    def alias_exists(self, alias: str) -> bool:
        return self.exists

    def create_index(self, alias: str, dim: int, meta: dict[str, Any]) -> str:
        self.meta = meta
        return f"{alias}-test"

    def copy_other_sources(self, alias: str, index: str, sources: list[str]) -> int:
        self.copied_excluding = sources
        return 0

    def bulk_index(self, index: str, documents: Iterable[ChunkDocument]) -> int:
        batch = list(documents)
        self.documents += batch
        return len(batch)

    def publish(self, alias: str, index: str) -> None:
        self.published = (alias, index)
