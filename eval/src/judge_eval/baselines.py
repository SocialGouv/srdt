"""Reference judges that need no model.

They are fitted on, or read, the human labels themselves, so they are *reference
lines* (what a trivial rule achieves), not valid judges. A real judge has to beat
them to be worth anything.
"""

from typing import Any

import numpy as np

from judge_eval.data import Criterion, Item
from judge_eval.judge import Verdict
from judge_eval.metrics import counts_from_labels, scores

PREFIX = "baseline:"


class _Baseline:
    concurrency = 1000
    criteria: tuple[Criterion, ...] = tuple(Criterion)

    def __init__(self, name: str):
        self.name = PREFIX + name
        self.concurrency_group = self.name

    def describe(self) -> dict[str, Any]:
        return {"kind": "baseline"}

    def predict(self, item: Item, criterion: Criterion) -> bool:
        raise NotImplementedError

    async def judge(self, item: Item, criterion: Criterion) -> Verdict:
        return Verdict(status="ok", label=self.predict(item, criterion))


class MajorityJudge(_Baseline):
    """Always answers the most frequent human label of the criterion."""

    def __init__(self, items: list[Item]):
        super().__init__("majority")
        self._majority = {
            c: sum(i.labels[c] for i in items) * 2 >= len(items) for c in Criterion
        }

    def describe(self) -> dict[str, Any]:
        return {
            "kind": "baseline",
            "majority": {c.value: v for c, v in self._majority.items()},
        }

    def predict(self, item: Item, criterion: Criterion) -> bool:
        return self._majority[criterion]


class LengthJudge(_Baseline):
    """Thresholds the answer length. Threshold and direction are chosen per
    criterion to maximise balanced accuracy on the whole dataset (in-sample, so
    optimistic)."""

    def __init__(self, items: list[Item]):
        super().__init__("length")
        lengths = np.array([len(i.answer) for i in items])
        candidates = np.unique(lengths)
        self._rule: dict[Criterion, tuple[int, bool]] = {}
        for criterion in Criterion:
            truth = np.array([i.labels[criterion] for i in items])
            best = (-1.0, 0, True)
            for threshold in candidates:
                for longer_is_oui in (True, False):
                    pred = (lengths > threshold) == longer_is_oui
                    balanced = float(
                        scores(counts_from_labels(truth, pred))["balanced_accuracy"]
                    )
                    if balanced > best[0]:
                        best = (balanced, int(threshold), longer_is_oui)
            self._rule[criterion] = (best[1], best[2])

    def describe(self) -> dict[str, Any]:
        return {
            "kind": "baseline",
            "rule": {
                c.value: {"threshold_chars": t, "longer_is_oui": longer}
                for c, (t, longer) in self._rule.items()
            },
        }

    def predict(self, item: Item, criterion: Criterion) -> bool:
        threshold, longer_is_oui = self._rule[criterion]
        return (len(item.answer) > threshold) == longer_is_oui


class CopyCorrectJudge(_Baseline):
    """For `suffisant` only: copies the *human* `correct_en_droit` label. It
    shows how much of `suffisant` is explained by legal correctness alone."""

    criteria = (Criterion.SUFFISANT,)

    def __init__(self) -> None:
        super().__init__("copy-correct")

    def predict(self, item: Item, criterion: Criterion) -> bool:
        return item.labels[Criterion.CORRECT_EN_DROIT]


def make_baselines(items: list[Item]) -> list[_Baseline]:
    return [MajorityJudge(items), LengthJudge(items), CopyCorrectJudge()]
