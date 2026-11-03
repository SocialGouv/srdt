"""Environment: acco-analysis/.env, then ingestion/.env for what it does not set."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out"


@dataclass(frozen=True)
class Settings:
    albert_endpoint: str
    albert_api_key: str
    embedding_model: str
    llm_model: str
    snapshot_dir: Path
    site_url: str  # where `publish` put the UI, for the links of the report


def load_settings() -> Settings:
    # load_dotenv never overrides a variable that is already set
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT.parent / "ingestion" / ".env")
    snapshot_dir = Path(os.environ.get("SNAPSHOT_LOCAL_DIR", "snapshots"))
    if not snapshot_dir.is_absolute():
        # relative to the folder of the .env that set it: ingestion/ by default
        snapshot_dir = ROOT.parent / "ingestion" / snapshot_dir
    return Settings(
        albert_endpoint=os.environ.get("ALBERT_ENDPOINT", "").rstrip("/"),
        albert_api_key=os.environ.get("ALBERT_API_KEY", ""),
        embedding_model=os.environ.get("ALBERT_VECTORISATION_MODEL", "BAAI/bge-m3"),
        llm_model=os.environ.get("ACCO_LLM_MODEL", "mistral-medium-3-5"),
        snapshot_dir=snapshot_dir,
        site_url=os.environ.get("ACCO_SITE_URL", "").rstrip("/"),
    )
