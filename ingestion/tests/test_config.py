from pathlib import Path

import pytest
from pydantic import ValidationError

from ingestion.config import Config, SyncConfig, load_config
from ingestion.contract import SOURCES

CONFIG_DIR = Path(__file__).parents[1] / "config"


def test_local_config_includes_every_source():
    config = load_config(CONFIG_DIR / "local.toml")
    assert set(config.include) == set(SOURCES)
    assert config.snapshot_ref("kali") == "latest"


def test_local_config_sync_guards():
    config = load_config(CONFIG_DIR / "local.toml")
    assert config.sync == SyncConfig(max_delete_ratio=0.10, min_deleted=25)


def test_sync_ratio_per_source():
    sync = SyncConfig(max_delete_ratio=0.1, per_source={"judilibre": 0.5})
    assert (sync.max_ratio("judilibre"), sync.max_ratio("conventions")) == (0.5, 0.1)


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
        {"sync": {"max_delete_ratio": 1.5}},
        {"sync": {"per_source": {"internet": 0.5}}},
    ],
)
def test_invalid_configs(fields):
    with pytest.raises(ValidationError):
        Config.model_validate(_config(**fields))
