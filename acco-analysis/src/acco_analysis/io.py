"""JSONL files of out/, one per stage."""

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from acco_analysis.settings import OUT


def path(name: str) -> Path:
    OUT.mkdir(exist_ok=True)
    return OUT / name


def write_jsonl(file: Path, rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    with open(file, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(file: Path) -> Iterator[dict[str, Any]]:
    with open(file) as f:
        for line in f:
            if line.strip():
                yield json.loads(line)
