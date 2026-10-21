from pathlib import Path

import pytest

from judge_eval.data import Criterion, Item

ROOT = Path(__file__).resolve().parents[1]
REAL_DATASET = ROOT / "dataset" / "18q_human.json"

requires_real_dataset = pytest.mark.skipif(
    not REAL_DATASET.exists(), reason="dataset/18q_human.json not available"
)


def make_item(
    item_id: str = "id_1",
    question_id: int = 0,
    answer: str = "Réponse.",
    correct: bool = True,
    sufficient: bool = True,
    intelligible: bool = True,
) -> Item:
    return Item(
        id=item_id,
        question_id=question_id,
        question="Question ?",
        answer=answer,
        labels={
            Criterion.CORRECT_EN_DROIT: correct,
            Criterion.SUFFISANT: sufficient,
            Criterion.INTELLIGIBLE: intelligible,
        },
    )
