import asyncio
import json

import pytest
from conftest import REAL_DATASET, make_item, requires_real_dataset

from judge_eval.baselines import make_baselines
from judge_eval.data import CRITERIA, Criterion, load_dataset
from judge_eval.judge import Verdict
from judge_eval.metrics import bootstrap_draws
from judge_eval.report import build_frame, metrics_table
from judge_eval.runner import (
    PREDICTIONS_FILE,
    RunConfigError,
    check_run_config,
    load_predictions,
    run_judges,
)

ITEMS = [make_item(f"id_{i}", question_id=i % 2, correct=i % 2 == 0) for i in range(4)]


class Gauge:
    """Counts calls in flight across several judges."""

    current = 0
    peak = 0


class FakeJudge:
    criteria = tuple(Criterion)

    def __init__(self, name="fake", outcomes=None, group=None, gauge=None, limit=3):
        self.name = name
        self.concurrency_group = group or name
        self.concurrency = limit
        self.gauge = gauge
        self.calls: list[tuple[str, str]] = []
        self.outcomes = outcomes or {}

    def describe(self):
        return {"kind": "fake"}

    async def judge(self, item, criterion):
        self.calls.append((item.id, criterion.value))
        if self.gauge:
            self.gauge.current += 1
            self.gauge.peak = max(self.gauge.peak, self.gauge.current)
        await asyncio.sleep(0.001)
        if self.gauge:
            self.gauge.current -= 1
        status = self.outcomes.get((item.id, criterion.value), "ok")
        if status == "ok":
            return Verdict(status="ok", label=True)
        return Verdict(status=status, error="simulated")


def run(judges, run_dir, items=ITEMS, criteria=CRITERIA):
    return asyncio.run(run_judges(judges, items, criteria, run_dir, "v1"))


def test_every_item_and_criterion_is_judged_once(tmp_path):
    judge = FakeJudge()
    summary = run([judge], tmp_path)
    assert summary.attempted == 12 and summary.ok == 12
    assert len(set(judge.calls)) == 12
    assert len(load_predictions(tmp_path / PREDICTIONS_FILE)) == 12


def test_rerun_makes_no_new_calls(tmp_path):
    run([FakeJudge()], tmp_path)
    again = FakeJudge()
    summary = run([again], tmp_path)
    assert again.calls == [] and summary.attempted == 0 and summary.skipped == 12


def test_api_errors_are_retried_but_parse_errors_are_final(tmp_path):
    first = FakeJudge(
        outcomes={
            ("id_0", "suffisant"): "api_error",
            ("id_1", "suffisant"): "parse_error",
        }
    )
    summary = run([first], tmp_path)
    assert (summary.ok, summary.parse_errors, summary.api_errors) == (10, 1, 1)

    second = FakeJudge()
    summary = run([second], tmp_path)
    assert second.calls == [("id_0", "suffisant")]
    stored = {
        (p.item_id, p.criterion.value): p.status
        for p in load_predictions(tmp_path / PREDICTIONS_FILE)
    }
    assert stored[("id_0", "suffisant")] == "ok"  # the retry replaced the error
    assert stored[("id_1", "suffisant")] == "parse_error"
    assert len(stored) == 12


def test_crash_leaving_a_partial_last_line_is_recoverable(tmp_path):
    run([FakeJudge()], tmp_path)
    path = tmp_path / PREDICTIONS_FILE
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n" + lines[-1][:30])  # cut mid-record

    assert len(load_predictions(path)) == 11
    resumed = FakeJudge()
    summary = run([resumed], tmp_path)
    assert summary.attempted == 1
    assert len(load_predictions(path)) == 12
    for line in path.read_text().splitlines():
        json.loads(line)  # no corrupt line left behind


def test_corruption_in_the_middle_is_reported(tmp_path):
    run([FakeJudge()], tmp_path)
    path = tmp_path / PREDICTIONS_FILE
    lines = path.read_text().splitlines()
    lines[3] = lines[3][:20]
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="corrupt record"):
        load_predictions(path)


def test_models_of_one_provider_share_its_concurrency_limit(tmp_path):
    gauge = Gauge()
    same_provider = [
        FakeJudge(f"p/m{i}", group="p", gauge=gauge, limit=2) for i in range(3)
    ]
    run(same_provider, tmp_path)
    assert gauge.peak == 2  # 3 models x 12 calls, never more than 2 at once

    other = Gauge()
    separate = [FakeJudge(f"q{i}", gauge=other, limit=2) for i in range(3)]
    (tmp_path / "separate").mkdir()
    run(separate, tmp_path / "separate")
    assert other.peak == 6  # independent groups each get their own limit


def test_judges_are_independent_and_criteria_are_respected(tmp_path):
    only_one = FakeJudge("a")
    only_one.criteria = (Criterion.SUFFISANT,)
    other = FakeJudge("b")
    run([only_one, other], tmp_path)
    assert {c for _, c in only_one.calls} == {"suffisant"}
    assert len(other.calls) == 12


def test_config_refuses_mixing_setups(tmp_path):
    def check(**overrides):
        args = {
            "dataset_sha256": "d1",
            "prompt_version": "v1",
            "prompt_sha256": "p1",
            "judges": [FakeJudge()],
        } | overrides
        check_run_config(tmp_path, **args)

    check()
    check()  # same setup: fine
    with pytest.raises(RunConfigError, match="dataset_sha256"):
        check(dataset_sha256="d2")
    with pytest.raises(RunConfigError, match="prompt_sha256"):
        check(prompt_sha256="p2")

    changed = FakeJudge()
    changed.describe = lambda: {"kind": "fake", "model": "other"}
    with pytest.raises(RunConfigError, match="settings of judge 'fake' changed"):
        check(judges=[changed])
    check(judges=[FakeJudge("new-judge")])  # adding a judge to a run is allowed


@requires_real_dataset
def test_baselines_reproduce_the_audit_numbers(tmp_path):
    items = load_dataset(REAL_DATASET)
    run(make_baselines(items), tmp_path, items=items)

    df = build_frame(items, load_predictions(tmp_path / PREDICTIONS_FILE))
    table = metrics_table(df, 18, bootstrap_draws(18, 200, seed=0))
    acc = {(r.slice, r.judge): r.accuracy for r in table.itertuples()}

    assert acc[("correct_en_droit", "baseline:majority")] == pytest.approx(114 / 184)
    assert acc[("suffisant", "baseline:majority")] == pytest.approx(97 / 184)
    assert acc[("intelligible", "baseline:majority")] == pytest.approx(123 / 184)
    assert acc[("suffisant", "baseline:copy-correct")] == pytest.approx(155 / 184)
    # copy-correct only exists for `suffisant`; length only beats majority in-sample
    assert ("correct_en_droit", "baseline:copy-correct") not in acc
    assert (
        acc[("intelligible", "baseline:length")]
        > acc[("intelligible", "baseline:majority")]
    )
    # conditional slice: the 114 answers the humans found correct (86 sufficient).
    # Global-majority and copy-correct are meaningless there and are left out.
    conditional = table[table["slice"] == "suffisant | correct=Oui"]
    assert list(conditional["judge"]) == ["baseline:length"]
    row = conditional.iloc[0]
    assert row["n_total"] == 114
    assert row["human_oui_rate"] == pytest.approx(86 / 114)
