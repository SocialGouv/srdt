"""The agreements of the latest `acco` snapshot (written by `ingest fetch acco`)."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ingestion.snapshots.store import LocalStore


@dataclass
class Agreement:
    id: str
    title: str
    company: str
    siret: str | None
    sector: str | None
    idcc: str | None
    nature: str | None
    signed: str | None  # YYYY-MM-DD
    themes: list[str] = field(default_factory=list)
    unions: list[str] = field(default_factory=list)
    text: str = ""
    content_source: str = "api"
    ape: str | None = None  # APE (NAF) code of the company, e.g. "8130Z"

    @property
    def url(self) -> str:
        return f"https://www.legifrance.gouv.fr/acco/id/{self.id}"


def _agreement(data: dict) -> Agreement:
    a = data["acco"]
    signed = a.get("dateTexte")
    idcc = a.get("codeIdcc")
    attachment = a.get("attachment") or {}
    return Agreement(
        id=a["id"],
        title=(a.get("titreTexte") or "").strip(),
        company=(a.get("raisonSociale") or "").strip(),
        siret=a.get("siret"),
        sector=a.get("secteur"),
        idcc=str(int(idcc)) if idcc and str(idcc).isdigit() else idcc,
        nature=a.get("nature"),
        signed=datetime.fromtimestamp(signed / 1000, UTC).date().isoformat()
        if isinstance(signed, int | float)
        else None,
        themes=[t["libelle"] for t in a.get("themes") or [] if t.get("libelle")],
        unions=[u["libelle"] for u in a.get("syndicats") or [] if u.get("libelle")],
        text=attachment.get("content") or "",
        content_source=attachment.get("content_source", "api"),
        ape=a.get("codeApe"),
    )


def load_agreements(snapshot_dir: Path) -> tuple[str, list[Agreement]]:
    """(snapshot id, agreements sorted by id)."""
    store = LocalStore(snapshot_dir)
    snapshot_id = store.latest("acco")
    manifest = store.manifest("acco", snapshot_id)
    agreements = [
        _agreement(json.loads(store.fetch_file(manifest, path).read_text()))
        for path in manifest.paths()
    ]
    return snapshot_id, sorted(agreements, key=lambda a: a.id)
