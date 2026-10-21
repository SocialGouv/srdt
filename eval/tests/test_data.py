import json
from collections import Counter

import pytest
from conftest import REAL_DATASET, requires_real_dataset

from judge_eval.data import Criterion, load_dataset


def _row(**overrides):
    row = {
        "id": "id_1",
        "question": "Q1",
        "reponse": "R1",
        "correct_en_droit": "Oui",
        "suffisant": "Non",
        "intelligible": "Oui",
    }
    return {**row, **overrides}


def _write(tmp_path, rows):
    path = tmp_path / "data.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_labels_become_booleans_and_questions_are_grouped(tmp_path):
    path = _write(
        tmp_path,
        [
            _row(id="a", question="Q1"),
            _row(id="b", question="Q2", correct_en_droit="Non"),
            _row(id="c", question="Q1", extra_column="ignored"),
        ],
    )
    items = load_dataset(path)
    assert [i.question_id for i in items] == [0, 1, 0]
    assert items[0].labels == {
        Criterion.CORRECT_EN_DROIT: True,
        Criterion.SUFFISANT: False,
        Criterion.INTELLIGIBLE: True,
    }
    assert items[1].labels[Criterion.CORRECT_EN_DROIT] is False
    assert items[0].answer == "R1"


@pytest.mark.parametrize(
    "bad_row",
    [
        _row(suffisant="oui"),
        _row(suffisant=None),
        _row(reponse=""),
        {k: v for k, v in _row().items() if k != "intelligible"},
    ],
)
def test_invalid_rows_are_rejected(tmp_path, bad_row):
    with pytest.raises(ValueError, match="row 0"):
        load_dataset(_write(tmp_path, [bad_row]))


def test_duplicate_ids_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicate id"):
        load_dataset(_write(tmp_path, [_row(), _row()]))


@requires_real_dataset
def test_real_dataset_matches_the_audit():
    items = load_dataset(REAL_DATASET)
    assert len(items) == 184
    assert len({i.question_id for i in items}) == 18
    oui = Counter()
    for item in items:
        for criterion, label in item.labels.items():
            oui[criterion] += label
    assert oui == {
        Criterion.CORRECT_EN_DROIT: 114,
        Criterion.SUFFISANT: 87,
        Criterion.INTELLIGIBLE: 123,
    }
