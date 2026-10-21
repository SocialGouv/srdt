"""Command line: `answer-eval contexts | prompts | generate | judge | report`.

Compares answer models on a fixed knowledge base: the prompt is the one the web
builds for `/api/generate`, the fiches are the documents a labeller graded useful.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from answer_eval.contexts import Context, build_contexts
from answer_eval.generate import (
    ANSWERS_FILE,
    CONFIG_FILE,
    CONTEXTS_FILE,
    RunConfigError,
    check_run_config,
    load_answers,
    load_contexts,
    render,
    run_generation,
)
from answer_eval.judging import answer_items, judge_dir
from answer_eval.prompt import WebPrompts, sha256_text
from answer_eval.report import build_report, write_csv
from judge_eval.cli import _describe_checks, _select_models
from judge_eval.data import CRITERIA, Criterion
from judge_eval.endpoints import check_models
from judge_eval.judge import ModelConfig, OpenAICompatibleJudge
from judge_eval.prompts import PromptBook
from judge_eval.runner import (
    PREDICTIONS_FILE,
    load_predictions,
    run_judges,
)
from judge_eval.runner import RunConfigError as JudgeRunConfigError
from judge_eval.runner import check_run_config as check_judge_config
from retrieval_eval.cli import api_base_url
from retrieval_eval.data import load_docs, load_qrels, load_queries
from retrieval_eval.pipeline import K_RERANK
from retrieval_eval.search_client import SearchAPI, SearchAPIError

ROOT = Path(__file__).resolve().parents[2]  # the eval/ directory
REPO_ROOT = ROOT.parent
DEFAULT_QRELS = (
    ROOT / "retrieval/qrels/llm-scaleway-llama-3.3-70b-instruct-v1-a3918e4a.jsonl"
)
DEFAULT_PROMPTS = ROOT / "generation/prompts/web-v2.0.json"


class SetupError(Exception):
    pass


def _run_dir(args: argparse.Namespace) -> Path:
    return args.runs_dir / args.run_id


def _web_prompts(path: Path) -> WebPrompts:
    prompts = WebPrompts(path)
    if stale := prompts.stale_sources(REPO_ROOT):
        print(
            f"Warning: {', '.join(stale)} changed since {path.name} was exported; "
            "the prompts may differ from the web's. Re-export with "
            "`node scripts/web_prompts.mjs export <new file>`.",
            file=sys.stderr,
        )
    return prompts


def _contexts(run_dir: Path) -> list[Context]:
    if not (run_dir / CONTEXTS_FILE).exists():
        raise SetupError(f"{run_dir / CONTEXTS_FILE} not found: run `contexts` first")
    return load_contexts(run_dir)


def _ranks(pairs_path: Path) -> dict[tuple[str, str], int]:
    """(query_id, doc_id) -> rank in the production ranking (hybrid + rerank)."""
    ranks = {}
    for line in pairs_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("rank_hybrid_rerank") is not None:
            ranks[(row["query_id"], row["doc_id"])] = row["rank_hybrid_rerank"]
    return ranks


def _preflight(configs: list[ModelConfig], skip: bool) -> None:
    if skip:
        return
    checks = asyncio.run(check_models(configs))
    for check in checks:
        if check.listed is None:
            print(
                f"Warning: could not verify model {check.config.model!r} "
                f"({check.error}); continuing.",
                file=sys.stderr,
            )
    if any(c.listed is False for c in checks):
        raise SetupError(
            _describe_checks(checks, show_all=False)
            + "\nFix the model id (see `judge-eval models --all --models FILE`) "
            "or pass --skip-check."
        )


def cmd_contexts(args: argparse.Namespace) -> int:
    run_dir = _run_dir(args)
    path = run_dir / CONTEXTS_FILE
    if path.exists() and not args.force:
        raise SetupError(
            f"{path} exists: the answers of this run were made from it. Use a new "
            "--run-id (or --force before any answer is generated)."
        )
    key = os.environ.get("AUTH_API_KEY")
    if not key:
        raise SetupError("AUTH_API_KEY is not set (the key of api/.env)")

    queries = [q for q in load_queries(args.queries) if q.source == args.source]
    if not queries:
        raise SetupError(f"no query with source {args.source!r} in {args.queries}")
    qrels = load_qrels(args.qrels)
    labellers = sorted({q.labeller for q in qrels})
    if args.labeller:
        qrels = [q for q in qrels if q.labeller == args.labeller]
    elif len(labellers) > 1:
        raise SetupError(f"choose the labeller with --labeller among {labellers}")
    if not qrels:
        raise SetupError(f"no labels in {args.qrels} for {args.labeller!r}")

    async def main() -> list[Context]:
        api = SearchAPI(api_base_url(), key)
        try:
            async with httpx.AsyncClient(timeout=30) as lookup:
                return await build_contexts(
                    queries,
                    qrels,
                    load_docs(args.docs),
                    _ranks(args.pairs),
                    api,
                    lookup,
                    min_grade=args.min_grade,
                    max_fiches=args.max_fiches,
                )
        finally:
            await api.aclose()

    contexts = asyncio.run(main())
    run_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(c.model_dump_json() + "\n" for c in contexts), encoding="utf-8"
    )
    for c in contexts:
        grades = "".join(str(f.grade) for f in c.fiches)
        print(
            f"  {c.query_id}  idcc={c.idcc or '-':5}  fiches={grades:10}  "
            f"code={len(c.code)}  cc={len(c.idcc_chunks)}",
            file=sys.stderr,
        )
    print(f"{len(contexts)} contexts written to {path}", file=sys.stderr)
    return 0


def cmd_prompts(args: argparse.Namespace) -> int:
    run_dir = _run_dir(args)
    contexts = _contexts(run_dir)
    prompts = _web_prompts(args.prompts)
    if args.query_id:
        context = next((c for c in contexts if c.query_id == args.query_id), None)
        if context is None:
            raise SetupError(f"unknown query id {args.query_id!r}")
        for message in render(prompts, context):
            print(f"--- {message['role']} ---\n{message['content']}\n")
        return 0
    path = run_dir / "prompts.jsonl"
    with path.open("w", encoding="utf-8") as out:
        for context in contexts:
            chat = render(prompts, context)
            record = {
                "query_id": context.query_id,
                "prompt_sha256": sha256_text(json.dumps(chat, ensure_ascii=False)),
                "system_chars": len(chat[0]["content"]),
                "messages": chat,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(
                f"  {context.query_id}  {record['system_chars']:>7} chars",
                file=sys.stderr,
            )
    print(f"Prompts written to {path}", file=sys.stderr)
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    run_dir = _run_dir(args)
    contexts = _contexts(run_dir)
    if args.limit:
        contexts = contexts[: args.limit]
    prompts = _web_prompts(args.prompts)
    generators = _select_models(args.models, args.only)
    if not generators:
        raise SetupError(f"no [[models]] in {args.models}")
    _preflight(generators, args.skip_check)
    check_run_config(run_dir, prompts, generators)
    print(
        f"Run {args.run_id}: {len(generators)} generator(s) x {len(contexts)} "
        "question(s)",
        file=sys.stderr,
    )
    summary = asyncio.run(run_generation(generators, contexts, prompts, run_dir))
    print(
        f"Done: {summary.attempted} new ({summary.ok} ok, {summary.empty} empty, "
        f"{summary.api_errors} API errors), {summary.skipped} already stored.",
        file=sys.stderr,
    )
    if summary.api_errors:
        print("Re-run the same command to retry the API errors.", file=sys.stderr)
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    run_dir = _run_dir(args)
    contexts = _contexts(run_dir)
    answers = load_answers(run_dir / ANSWERS_FILE)
    if args.generators:
        wanted = {g.strip() for g in args.generators.split(",")}
        answers = [a for a in answers if a.generator in wanted]
    items = answer_items(answers, contexts)
    if not items:
        raise SetupError("no generated answer to judge: run `generate` first")

    configs = _select_models(args.judges, args.only)
    _preflight(configs, args.skip_check)
    book = PromptBook(args.judge_prompts_dir, args.judge_prompt_version)
    judges = [OpenAICompatibleJudge(c, book) for c in configs]
    criteria = (
        [Criterion(c) for c in args.criteria] if args.criteria else list(CRITERIA)
    )
    out_dir = judge_dir(run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    config = json.loads((run_dir / CONFIG_FILE).read_text(encoding="utf-8"))
    check_judge_config(
        out_dir,
        dataset_sha256=config["contexts_sha256"],
        prompt_version=book.version,
        prompt_sha256=book.sha256,
        judges=judges,
    )
    print(
        f"Judging {len(items)} answer(s) with {len(judges)} judge(s), "
        f"{len(criteria)} criterion(a) -> {out_dir}",
        file=sys.stderr,
    )
    summary = asyncio.run(run_judges(judges, items, criteria, out_dir, book.version))
    print(
        f"Done: {summary.attempted} new ({summary.ok} ok, {summary.parse_errors} "
        f"parse errors, {summary.api_errors} API errors), "
        f"{summary.skipped} already stored.",
        file=sys.stderr,
    )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = _run_dir(args)
    contexts = _contexts(run_dir)
    answers = load_answers(run_dir / ANSWERS_FILE)
    if not answers:
        raise SetupError("the run has no answers yet")
    predictions = load_predictions(judge_dir(run_dir) / PREDICTIONS_FILE)
    summary, side_by_side, rows = build_report(
        args.run_id, contexts, answers, predictions
    )
    (run_dir / "report.md").write_text(summary, encoding="utf-8")
    (run_dir / "answers.md").write_text(side_by_side, encoding="utf-8")
    write_csv(run_dir / "per_answer.csv", rows)
    print(summary)
    print(
        f"Written: report.md, answers.md, per_answer.csv in {run_dir}",
        file=sys.stderr,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="answer-eval", description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "runs")
    sub = parser.add_subparsers(dest="command", required=True)

    contexts = sub.add_parser(
        "contexts", help="Freeze the knowledge base of each question (calls the API)"
    )
    contexts.add_argument("--run-id", required=True)
    contexts.add_argument(
        "--queries", type=Path, default=ROOT / "retrieval/queries.jsonl"
    )
    contexts.add_argument("--source", default="idcc22", help="Query set to answer")
    contexts.add_argument("--qrels", type=Path, default=DEFAULT_QRELS)
    contexts.add_argument("--labeller", help="Labeller to read from --qrels")
    contexts.add_argument(
        "--docs", type=Path, default=ROOT / "retrieval/dataset/documents.jsonl"
    )
    contexts.add_argument(
        "--pairs",
        type=Path,
        default=ROOT / "retrieval/dataset/pairs.jsonl",
        help="Production ranks, to order fiches of equal grade",
    )
    contexts.add_argument("--min-grade", type=int, default=1, choices=(1, 2))
    contexts.add_argument("--max-fiches", type=int, default=K_RERANK)
    contexts.add_argument("--force", action="store_true")
    contexts.set_defaults(func=cmd_contexts)

    prompts = sub.add_parser("prompts", help="Write (or show) the rendered prompts")
    prompts.add_argument("--run-id", required=True)
    prompts.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    prompts.add_argument("--query-id", help="Print the messages of one question")
    prompts.set_defaults(func=cmd_prompts)

    generate = sub.add_parser("generate", help="Answer every question (resumable)")
    generate.add_argument("--run-id", required=True)
    generate.add_argument(
        "--models", type=Path, default=ROOT / "config/generators.toml"
    )
    generate.add_argument("--only", help="Comma-separated model or provider names")
    generate.add_argument("--limit", type=int, help="Only the first N questions")
    generate.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    generate.add_argument("--skip-check", action="store_true")
    generate.set_defaults(func=cmd_generate)

    judge = sub.add_parser("judge", help="Judge the answers (resumable)")
    judge.add_argument("--run-id", required=True)
    judge.add_argument("--judges", type=Path, default=ROOT / "config/models.toml")
    judge.add_argument("--only", help="Comma-separated judge or provider names")
    judge.add_argument("--generators", help="Comma-separated generators to judge")
    judge.add_argument("--criteria", nargs="+", choices=[c.value for c in CRITERIA])
    judge.add_argument("--judge-prompt-version", default="v1")
    judge.add_argument("--judge-prompts-dir", type=Path, default=ROOT / "prompts")
    judge.add_argument("--skip-check", action="store_true")
    judge.set_defaults(func=cmd_judge)

    report = sub.add_parser("report", help="Summary and side-by-side answers")
    report.add_argument("--run-id", required=True)
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (
        SetupError,
        RunConfigError,
        JudgeRunConfigError,
        SearchAPIError,
        httpx.HTTPError,
        FileNotFoundError,
        RuntimeError,
        ValueError,
    ) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
