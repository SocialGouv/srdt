from pathlib import Path

import pytest
from pydantic import ValidationError

from ingestion.config import Config, load_config
from ingestion.contract import SOURCES

CONFIG_DIR = Path(__file__).parents[1] / "config"


def test_local_config_includes_every_source():
    config = load_config(CONFIG_DIR / "local.toml")
    assert set(config.include) == set(SOURCES)
    assert config.snapshot_ref("kali") == "latest"


def _config(**fields) -> dict:
    return {"include": ["judilibre"], "embedding": {"model_id": "m"}, **fields}


def test_snapshots_default_to_latest():
    assert Config.model_validate(_config()).snapshot_ref("legi") == "latest"


@pytest.mark.parametrize(
    "fields",
    [
        {"include": ["internet"]},
        {"include": ["judilibre", "judilibre"]},
        {"include": []},
        {"snapshots": {"unknown": "latest"}},
        {"unknown": 1},
    ],
)
def test_invalid_configs(fields):
    with pytest.raises(ValidationError):
        Config.model_validate(_config(**fields))
