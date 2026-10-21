"""Append-only JSONL files that survive a crash mid-write."""

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel


def repair_trailing_partial_line(path: Path) -> None:
    """Drop an incomplete last line left by a crash, so appends stay valid."""
    if not path.exists():
        return
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        path.write_bytes(data[: data.rfind(b"\n") + 1])


def read_jsonl[M: BaseModel](path: Path, model: type[M]) -> Iterator[M]:
    """Records in file order. A partial last line (crash) is ignored; a corrupt line
    anywhere else is an error."""
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            yield model.model_validate_json(line)
        except ValueError as e:
            if number == len(lines):
                continue
            raise ValueError(f"{path}:{number}: corrupt record: {e}") from e


def append_jsonl(path: Path, records: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    repair_trailing_partial_line(path)
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False))
            f.write("\n")
