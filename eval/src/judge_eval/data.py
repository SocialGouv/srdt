"""Loading and validation of the human-labelled answers."""

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Criterion(StrEnum):
    CORRECT_EN_DROIT = "correct_en_droit"
    SUFFISANT = "suffisant"
    INTELLIGIBLE = "intelligible"


CRITERIA: tuple[Criterion, ...] = tuple(Criterion)

YesNo = Literal["Oui", "Non"]


class RawRecord(BaseModel):
    """One row of the JSON file, exactly as annotated. Unknown columns are ignored."""

    model_config = ConfigDict(extra="ignore")

    id: str
    question: str = Field(min_length=1)
    reponse: str = Field(min_length=1)
    correct_en_droit: YesNo
    suffisant: YesNo
    intelligible: YesNo


class Item(BaseModel):
    """A (question, answer) pair with its human verdicts (True = "Oui"). Answers
    that are only judged, never compared with humans (answer_eval), have none."""

    model_config = ConfigDict(frozen=True)

    id: str
    # Index of the question in order of first appearance. Answers sharing a
    # question_id are correlated: group by it for any split or resampling.
    question_id: int
    question: str
    answer: str
    labels: dict[Criterion, bool] = Field(default_factory=dict)


def load_dataset(path: Path) -> list[Item]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a JSON list of records")

    question_ids: dict[str, int] = {}
    seen_ids: set[str] = set()
    items: list[Item] = []
    for index, row in enumerate(rows):
        try:
            record = RawRecord.model_validate(row)
        except ValidationError as e:
            raise ValueError(f"{path}: row {index} is invalid:\n{e}") from e
        if record.id in seen_ids:
            raise ValueError(f"{path}: duplicate id {record.id!r} (row {index})")
        seen_ids.add(record.id)

        question_id = question_ids.setdefault(record.question, len(question_ids))
        items.append(
            Item(
                id=record.id,
                question_id=question_id,
                question=record.question,
                answer=record.reponse,
                labels={c: getattr(record, c.value) == "Oui" for c in CRITERIA},
            )
        )
    return items


def dataset_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
