"""Runs judges over the dataset and stores every outcome in a run directory.

runs/<run_id>/
    config.json        dataset/prompt hashes and the settings of each judge
    predictions.jsonl  one line per (judge, item, criterion), append-only

A run is resumable: re-running skips what is already stored. `api_error` results
(no answer obtained) are retried; `ok` and `parse_error` ones are final.
"""

import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from judge_eval.data import Criterion, Item
from judge_eval.judge import Judge, Verdict

PREDICTIONS_FILE = "predictions.jsonl"
CONFIG_FILE = "config.json"

Key = tuple[str, str, str, str]  # judge, prompt_version, item_id, criterion


class Prediction(Verdict):
    judge: str
    prompt_version: str
    item_id: str
    criterion: Criterion

    @property
    def key(self) -> Key:
        return (self.judge, self.prompt_version, self.item_id, self.criterion.value)


class RunConfigError(RuntimeError):
    pass


@dataclass
class RunSummary:
    attempted: int = 0
    skipped: int = 0
    ok: int = 0
    parse_errors: int = 0
    api_errors: int = 0


def _repair_trailing_partial_line(path: Path) -> None:
    """Drop an incomplete last line left by a crash, so appends stay valid."""
    if not path.exists():
        return
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        path.write_bytes(data[: data.rfind(b"\n") + 1])


def load_predictions(path: Path) -> list[Prediction]:
    """Latest record per key, in file order of the latest occurrence."""
    if not path.exists():
        return []
    latest: dict[Key, Prediction] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            prediction = Prediction.model_validate_json(line)
        except ValueError as e:
            if number == len(lines):  # partial last line from a crash
                continue
            raise ValueError(f"{path}:{number}: corrupt record: {e}") from e
        latest.pop(prediction.key, None)
        latest[prediction.key] = prediction
    return list(latest.values())


def check_run_config(
    run_dir: Path,
    *,
    dataset_sha256: str,
    prompt_version: str,
    prompt_sha256: str,
    judges: Sequence[Judge],
) -> None:
    """Create or update config.json; refuse to mix results from different setups."""
    path = run_dir / CONFIG_FILE
    config: dict = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset_sha256": dataset_sha256,
        "prompt_version": prompt_version,
        "prompt_sha256": prompt_sha256,
        "judges": {},
    }
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        for field in ("dataset_sha256", "prompt_version", "prompt_sha256"):
            if existing[field] != config[field]:
                raise RunConfigError(
                    f"{path}: {field} differs from this run's setup "
                    f"({existing[field]!r} vs {config[field]!r}). "
                    "Use a new --run-id instead of mixing results."
                )
        config = existing
    for judge in judges:
        settings = judge.describe()
        previous = config["judges"].get(judge.name)
        if previous is not None and previous != settings:
            raise RunConfigError(
                f"{path}: settings of judge {judge.name!r} changed since the run "
                "started. Use a new --run-id."
            )
        config["judges"][judge.name] = settings
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


async def run_judges(
    judges: Sequence[Judge],
    items: Sequence[Item],
    criteria: Sequence[Criterion],
    run_dir: Path,
    prompt_version: str,
) -> RunSummary:
    predictions_path = run_dir / PREDICTIONS_FILE
    _repair_trailing_partial_line(predictions_path)
    final = {
        p.key for p in load_predictions(predictions_path) if p.status != "api_error"
    }

    summary = RunSummary()
    pending: list[tuple[Judge, Item, Criterion]] = []
    for judge in judges:
        for item in items:
            for criterion in criteria:
                if criterion not in judge.criteria:
                    continue
                key = (judge.name, prompt_version, item.id, criterion.value)
                if key in final:
                    summary.skipped += 1
                else:
                    pending.append((judge, item, criterion))

    semaphores: dict[str, asyncio.Semaphore] = {}
    for judge in judges:
        semaphores.setdefault(
            judge.concurrency_group, asyncio.Semaphore(judge.concurrency)
        )
    write_lock = asyncio.Lock()
    total = len(pending)

    with predictions_path.open("a", encoding="utf-8") as out:

        async def work(judge: Judge, item: Item, criterion: Criterion) -> None:
            async with semaphores[judge.concurrency_group]:
                verdict = await judge.judge(item, criterion)
            prediction = Prediction(
                **verdict.model_dump(),
                judge=judge.name,
                prompt_version=prompt_version,
                item_id=item.id,
                criterion=criterion,
            )
            async with write_lock:
                out.write(prediction.model_dump_json() + "\n")
                out.flush()
                summary.attempted += 1
                if verdict.status == "ok":
                    summary.ok += 1
                elif verdict.status == "parse_error":
                    summary.parse_errors += 1
                else:
                    summary.api_errors += 1
                if summary.attempted % 25 == 0 or summary.attempted == total:
                    print(
                        f"  {summary.attempted}/{total} done "
                        f"({summary.parse_errors} parse errors, "
                        f"{summary.api_errors} API errors)",
                        file=sys.stderr,
                    )

        await asyncio.gather(*(work(*task) for task in pending))
    return summary
