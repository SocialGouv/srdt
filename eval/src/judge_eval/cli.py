"""Command line: `judge-eval run | report | prompt | models | check`."""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from judge_eval.baselines import make_baselines
from judge_eval.data import CRITERIA, Criterion, Item, dataset_sha256, load_dataset
from judge_eval.endpoints import ModelCheck, ModelProbe, check_models, probe_models
from judge_eval.judge import Judge, ModelConfig, OpenAICompatibleJudge, load_models
from judge_eval.metrics import bootstrap_draws
from judge_eval.prompts import PromptBook
from judge_eval.report import (
    build_frame,
    disagreements_table,
    metrics_table,
    pairwise_table,
    per_question_table,
    render_markdown,
)
from judge_eval.runner import (
    CONFIG_FILE,
    PREDICTIONS_FILE,
    RunConfigError,
    check_run_config,
    load_predictions,
    run_judges,
)

ROOT = Path(__file__).resolve().parents[2]  # the eval/ directory


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset/18q_human.json")
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "runs")


def _spread(items: list[Item], limit: int) -> list[Item]:
    """`limit` items spread evenly over the dataset (so over several questions)."""
    step = max(1, len(items) // limit)
    return items[::step][:limit]


def _find_item(items: list[Item], item_id: str | None) -> Item | None:
    """The item with this id, the first one when no id is given, None if unknown."""
    if not item_id:
        return items[0]
    return next((i for i in items if i.id == item_id), None)


def _select_models(path: Path, only: str | None) -> list[ModelConfig]:
    """Models of the file, optionally restricted to some model/provider names."""
    configs = load_models(path)
    if only:
        wanted = {w.strip() for w in only.split(",")}
        known = {c.name for c in configs} | {c.provider for c in configs}
        if unknown := wanted - known:
            raise ValueError(
                f"Unknown model or provider name(s): {sorted(unknown)}; "
                f"known: {sorted(known)}"
            )
        configs = [c for c in configs if c.name in wanted or c.provider in wanted]
    return configs


def _describe_checks(checks: list[ModelCheck], show_all: bool) -> str:
    """One block per endpoint: the status of each configured model, and the ids it
    serves (always when `show_all`, otherwise only if one of the models is missing)."""
    endpoints: dict[tuple[str, str | None], list[ModelCheck]] = {}
    for check in checks:
        key = (check.config.base_url, check.config.api_key_env)
        endpoints.setdefault(key, []).append(check)

    blocks = []
    for group in endpoints.values():
        first = group[0]
        label = first.config.provider or first.config.name
        lines = [f"{label}  ({first.config.base_url})"]
        if first.available is None:
            lines.append(f"  could not list the models of this endpoint: {first.error}")
            lines += [f"  ?           {c.config.model}" for c in group]
        else:
            for c in group:
                status = "OK        " if c.listed else "NOT SERVED"
                lines.append(f"  {status}  {c.config.model}")
            if show_all or not all(c.listed for c in group):
                ids = ", ".join(sorted(first.available)) or "(none)"
                lines.append(f"  available ({len(first.available)}): {ids}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def cmd_models(args: argparse.Namespace) -> int:
    """Check that the configured model ids exist on their endpoints."""
    configs = _select_models(args.models, args.only)
    checks = asyncio.run(check_models(configs))
    print(_describe_checks(checks, args.all))
    return 1 if any(c.listed is False for c in checks) else 0


def _describe_probes(probes: list[ModelProbe]) -> str:
    """A row per model (what it answered and how), then the details of each failure."""
    rows = [("MODEL", "RESULT", "MODE", "FINISH", "LATENCY", "OUT TOKENS", "SERVED AS")]
    notes = []
    for probe in probes:
        name, verdict = probe.config.name, probe.verdict
        if verdict is None:
            rows.append((name, "NOT CALLED", "-", "-", "-", "-", "-"))
            notes.append(f"  {name}: {probe.skipped}")
            continue
        if verdict.status == "ok":
            result = f"ok ({'Oui' if verdict.label else 'Non'})"
        else:
            result = verdict.status.replace("_", " ").upper()
            notes.append(f"  {name}: {verdict.error}")
        if verdict.status == "parse_error":
            notes.append(f"    reply: {(verdict.raw or '')[:200]!r}")
            if verdict.finish_reason == "length":
                notes.append(
                    "    cut off by the token limit: raise it with "
                    "params = { temperature = 0, max_tokens = N } on this entry"
                )
        served = verdict.served_model
        rows.append(
            (
                name,
                result,
                verdict.response_mode or "-",
                verdict.finish_reason or "-",
                "-" if verdict.latency_s is None else f"{verdict.latency_s:.1f}s",
                "-"
                if verdict.completion_tokens is None
                else str(verdict.completion_tokens),
                served if served and served != probe.config.model else "-",
            )
        )

    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = [
        "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip()
        for row in rows
    ]
    if notes:
        lines += ["", *notes]
    lines += ["", f"{sum(p.ok for p in probes)}/{len(probes)} model(s) OK"]
    return "\n".join(lines)


def cmd_check(args: argparse.Namespace) -> int:
    """Judge one item with every model and report what each one answered."""
    items = load_dataset(args.dataset)
    item = _find_item(items, args.item)
    if item is None:
        print(f"Unknown item id {args.item!r}", file=sys.stderr)
        return 2
    configs = _select_models(args.models, args.only)
    prompts = PromptBook(args.prompts_dir, args.prompt_version)
    print(
        f"Probing {len(configs)} model(s) with item {item.id}, "
        f"criterion {args.criterion}...",
        file=sys.stderr,
    )
    probes = asyncio.run(
        probe_models(configs, item, Criterion(args.criterion), prompts)
    )
    print(_describe_probes(probes))
    return 0 if all(p.ok for p in probes) else 1


def cmd_run(args: argparse.Namespace) -> int:
    if not args.baselines and not args.models:
        print("Nothing to run: pass --baselines and/or --models FILE", file=sys.stderr)
        return 2

    items = load_dataset(args.dataset)
    prompts = PromptBook(args.prompts_dir, args.prompt_version)

    judges: list[Judge] = []
    if args.baselines:
        judges += make_baselines(items)  # fitted on the whole dataset
    if args.models:
        configs = _select_models(args.models, args.only)
        if not args.skip_check:
            # One cheap request per endpoint instead of hundreds of failing calls.
            checks = asyncio.run(check_models(configs))
            for check in checks:
                if check.listed is None:
                    print(
                        f"Warning: could not verify model {check.config.model!r} "
                        f"({check.error}); continuing.",
                        file=sys.stderr,
                    )
            if any(c.listed is False for c in checks):
                print(_describe_checks(checks, show_all=False), file=sys.stderr)
                print(
                    "Fix the model id (see `judge-eval models --all`) or pass "
                    "--skip-check.",
                    file=sys.stderr,
                )
                return 2
        judges += [OpenAICompatibleJudge(c, prompts) for c in configs]

    criteria = (
        [Criterion(c) for c in args.criteria] if args.criteria else list(CRITERIA)
    )
    selected = _spread(items, args.limit) if args.limit else items

    run_dir = args.runs_dir / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    check_run_config(
        run_dir,
        dataset_sha256=dataset_sha256(args.dataset),
        prompt_version=prompts.version,
        prompt_sha256=prompts.sha256,
        judges=judges,
    )
    print(
        f"Run {args.run_id}: {len(judges)} judge(s), {len(selected)} item(s), "
        f"{len(criteria)} criterion(a) -> {run_dir}",
        file=sys.stderr,
    )
    summary = asyncio.run(
        run_judges(judges, selected, criteria, run_dir, prompts.version)
    )
    print(
        f"Done: {summary.attempted} new ({summary.ok} ok, {summary.parse_errors} "
        f"parse errors, {summary.api_errors} API errors), "
        f"{summary.skipped} already stored.",
        file=sys.stderr,
    )
    if summary.api_errors:
        print("Re-run the same command to retry the API errors.", file=sys.stderr)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = args.runs_dir / args.run_id
    config_path = run_dir / CONFIG_FILE
    if not config_path.exists():
        print(f"No run found at {run_dir}", file=sys.stderr)
        return 2
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config["dataset_sha256"] != dataset_sha256(args.dataset):
        print(
            "Warning: the dataset changed since this run was made; results may not "
            "match the labels the judges were compared with.",
            file=sys.stderr,
        )

    items = load_dataset(args.dataset)
    predictions = load_predictions(run_dir / PREDICTIONS_FILE)
    if not predictions:
        print("The run has no predictions yet.", file=sys.stderr)
        return 2
    n_clusters = len({i.question_id for i in items})
    draws = bootstrap_draws(n_clusters, args.bootstrap, args.seed)

    df = build_frame(items, predictions)
    metrics = metrics_table(df, n_clusters, draws)
    pairwise = pairwise_table(df, n_clusters, draws)
    markdown = render_markdown(
        metrics,
        pairwise,
        run_name=args.run_id,
        n_clusters=n_clusters,
        n_boot=args.bootstrap,
    )

    (run_dir / "report.md").write_text(markdown, encoding="utf-8")
    metrics.to_csv(run_dir / "metrics.csv", index=False)
    pairwise.to_csv(run_dir / "pairwise.csv", index=False)
    per_question_table(df).to_csv(run_dir / "per_question.csv", index=False)
    disagreements_table(df, items).to_csv(run_dir / "disagreements.csv", index=False)
    print(markdown)
    print(f"Files written to {run_dir}", file=sys.stderr)
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    """Print exactly what would be sent to a model for one item."""
    items = load_dataset(args.dataset)
    prompts = PromptBook(args.prompts_dir, args.prompt_version)
    item = _find_item(items, args.item)
    if item is None:
        print(f"Unknown item id {args.item!r}", file=sys.stderr)
        return 2
    for message in prompts.render(item, Criterion(args.criterion)):
        print(f"--- {message['role']} ---\n{message['content']}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(prog="judge-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Judge the dataset (resumable)")
    _add_common(run)
    run.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    run.add_argument("--models", type=Path, help="TOML file listing [[models]]")
    run.add_argument(
        "--only", help="Comma-separated model or provider names to keep from --models"
    )
    run.add_argument("--baselines", action="store_true", help="Also run the baselines")
    run.add_argument(
        "--skip-check",
        action="store_true",
        help="Do not verify the model ids against the endpoints before running",
    )
    run.add_argument("--criteria", nargs="+", choices=[c.value for c in CRITERIA])
    run.add_argument(
        "--limit", type=int, help="Judge only N items spread over the dataset"
    )
    run.add_argument("--prompt-version", default="v1")
    run.add_argument("--prompts-dir", type=Path, default=ROOT / "prompts")
    run.set_defaults(func=cmd_run)

    report = sub.add_parser("report", help="Compute metrics for a run")
    _add_common(report)
    report.add_argument("--run-id", required=True)
    report.add_argument("--bootstrap", type=int, default=1000)
    report.add_argument("--seed", type=int, default=0)
    report.set_defaults(func=cmd_report)

    prompt = sub.add_parser("prompt", help="Show the messages sent for one item")
    _add_common(prompt)
    prompt.add_argument("--item", help="Item id (default: first)")
    prompt.add_argument(
        "--criterion", choices=[c.value for c in CRITERIA], required=True
    )
    prompt.add_argument("--prompt-version", default="v1")
    prompt.add_argument("--prompts-dir", type=Path, default=ROOT / "prompts")
    prompt.set_defaults(func=cmd_prompt)

    models = sub.add_parser(
        "models", help="Check configured model ids on their endpoints"
    )
    models.add_argument("--models", type=Path, default=ROOT / "config/models.toml")
    models.add_argument(
        "--only", help="Comma-separated model or provider names to check"
    )
    models.add_argument("--all", action="store_true", help="Always list available ids")
    models.set_defaults(func=cmd_models)

    check = sub.add_parser(
        "check",
        help="Judge one item with every model to see that each one really works",
    )
    check.add_argument("--models", type=Path, default=ROOT / "config/models.toml")
    check.add_argument(
        "--only", help="Comma-separated model or provider names to check"
    )
    check.add_argument("--dataset", type=Path, default=ROOT / "dataset/18q_human.json")
    check.add_argument("--item", help="Item id (default: first)")
    check.add_argument(
        "--criterion",
        choices=[c.value for c in CRITERIA],
        default=Criterion.CORRECT_EN_DROIT.value,
    )
    check.add_argument("--prompt-version", default="v1")
    check.add_argument("--prompts-dir", type=Path, default=ROOT / "prompts")
    check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, RunConfigError, FileNotFoundError, ValueError) as e:
        # Setup problems (missing key, bad config/dataset, mixed runs): no traceback.
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
