"""Command line of the retrieval eval: `retrieval-eval --help`.

Order of use: sample-queries / add-queries (once), pool, label, audit-export,
audit-import, agreement, report. `pool` calls the SRDT API (ES + Albert rerank);
`label` calls a chat model and is the only costly step: it prints the size of the run
first, `--dry-run` stops there.
"""

import argparse
import asyncio
import os
import re
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # the eval/ directory
DEFAULT_QUERIES = ROOT / "retrieval/queries.jsonl"
QRELS_DIR = ROOT / "retrieval/qrels"
PROMPTS_DIR = ROOT / "retrieval/prompts"
LABELLERS_CONFIG = ROOT / "config/labellers.toml"  # candidates, apart from models.toml
LOCAL_DIR = ROOT / "retrieval/.local"
DEFAULT_API_URL = "http://localhost:8000"  # same default as web/src/modules/api


class SetupError(Exception):
    """A usage or configuration problem, reported as one line."""


def api_base_url() -> str:
    """API_BASE_URL without the `/api/v1` suffix the client adds itself (some env
    files, e.g. srdt-dataset's SRDT_API_URL, include it)."""
    url = os.environ.get("API_BASE_URL", DEFAULT_API_URL).rstrip("/")
    return url.removesuffix("/api/v1")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", text.lower()).strip("-")


def _run_dir(args: argparse.Namespace) -> Path:
    return args.runs_dir / args.run_id


def _select_queries(args: argparse.Namespace):
    from retrieval_eval.data import load_queries

    split = None if args.split == "all" else args.split
    queries = load_queries(args.queries, split)
    if getattr(args, "source", None):
        queries = [q for q in queries if q.source == args.source]
    if getattr(args, "limit", None):
        step = max(len(queries) // args.limit, 1)
        queries = queries[::step][: args.limit]  # spread over the file, not the head
    return queries


# --- queries -----------------------------------------------------------------


def _require_anonymiser():
    try:
        from retrieval_eval.anonymise import anonymise

        anonymise("test")  # fail now, not after the work, if spaCy is missing
    except (ImportError, OSError):  # no spaCy, or no model
        print(
            "spaCy and fr_core_news_md are required: uv sync --extra anonymise",
            file=sys.stderr,
        )
        return None
    return anonymise


def cmd_sample_queries(args: argparse.Namespace) -> int:
    from retrieval_eval.queries import (
        build_query_set,
        load_golden,
        read_export,
        write_audit,
        write_queries,
    )

    anonymise = _require_anonymiser()
    if anonymise is None:
        return 2

    if args.out.exists() and not args.force:
        print(
            f"{args.out} exists (the split is fixed once): use --force", file=sys.stderr
        )
        return 1

    query_set = build_query_set(
        rows=read_export(args.csv),
        golden=load_golden(args.golden),
        anonymise=anonymise,
        n=args.n,
        seed=args.seed,
        user_cap=args.user_cap,
        dev_size=args.dev_size,
    )
    write_queries(args.out, query_set.queries, force=args.force)
    write_audit(args.audit, query_set.audit)
    print(query_set.report)
    print(f"\nWrote {len(query_set.queries)} queries to {args.out}")
    print(f"Review the anonymisation in {args.audit} (local, not committed)")
    return 0


def cmd_add_queries(args: argparse.Namespace) -> int:
    from retrieval_eval.queries import (
        append_audit,
        append_queries,
        append_records,
        load_questions_with_idcc,
        read_queries,
    )

    anonymise = _require_anonymiser()
    if anonymise is None:
        return 2
    if not args.out.exists():
        print(f"{args.out} not found: run sample-queries first", file=sys.stderr)
        return 1

    existing = read_queries(args.out)
    result = append_queries(
        existing=existing,
        questions=load_questions_with_idcc(args.file),
        source=args.source,
        anonymise=anonymise,
        seed=args.seed,
    )
    print(
        f"{len(result.queries)} new, {len(result.skipped)} already present, "
        f"{len(result.near_existing)} close to an existing query"
    )
    if args.dry_run:
        return 0
    append_records(args.out, result.queries)
    append_audit(args.audit, result.audit)
    split = Counter(r["split"] for r in result.queries)
    print(f"Appended to {args.out} (dev {split['dev']}, test {split['test']})")
    print(f"Review the anonymisation in {args.audit} (local, not committed)")
    return 0


# --- pool --------------------------------------------------------------------


def cmd_pool(args: argparse.Namespace) -> int:
    from retrieval_eval.data import dataset_sha256, load_rankings
    from retrieval_eval.pool import (
        RANKINGS_FILE,
        check_pool_config,
        describe_rankings,
        fetch_docs,
        rank_queries,
    )
    from retrieval_eval.search_client import SearchAPI

    key = os.environ.get("AUTH_API_KEY")
    if not key:
        raise SetupError(
            "AUTH_API_KEY is not set (the key of api/.env, see .env.example)"
        )
    queries = _select_queries(args)
    run_dir = _run_dir(args)
    check_pool_config(
        run_dir,
        queries_sha256=dataset_sha256(args.queries),
        top_k=args.top_k,
        variants=args.variants,
    )

    def progress(done: int, total: int) -> None:
        print(f"\rranked {done}/{total} queries", end="", file=sys.stderr, flush=True)

    async def main() -> int:
        api = SearchAPI(
            api_base_url(),
            key,
            max_retries=args.max_retries,
        )
        try:
            summary = await rank_queries(
                api,
                queries,
                run_dir,
                variants=args.variants,
                top_k=args.top_k,
                concurrency=args.concurrency,
                on_progress=progress,
            )
            print(file=sys.stderr)
            fetched, missing = await fetch_docs(
                api, run_dir, depth=args.depth, concurrency=args.concurrency
            )
        finally:
            await api.aclose()
        print(
            f"ranked {summary.ranked}, already done {summary.skipped}, "
            f"failed {len(summary.failed)}; documents fetched {fetched}, "
            f"not returned by the API {len(missing)}"
        )
        for query_id, error in list(summary.failed.items())[:5]:
            print(f"  {query_id}: {error}", file=sys.stderr)
        rankings = load_rankings(run_dir / RANKINGS_FILE)
        print(describe_rankings(rankings, args.depth))
        return 1 if summary.failed else 0

    return asyncio.run(main())


# --- checking against the web --------------------------------------------------


def cmd_web_snapshot(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    from retrieval_eval.search_client import SearchAPI
    from retrieval_eval.web_check import (
        WebClient,
        find_snapshot,
        new_snapshot_dir,
        snapshot_port_only,
        snapshot_queries,
        write_meta,
    )

    if args.port_only and args.no_port:
        raise SetupError("--port-only and --no-port exclude each other")
    web_url = os.environ.get("WEB_BASE_URL", "")
    debug_key = os.environ.get("DEBUG_API_KEY", "")
    if not args.port_only and (not web_url or not debug_key):
        raise SetupError(
            "WEB_BASE_URL and DEBUG_API_KEY must be set (DEBUG_API_KEY: the web's), "
            "or use --port-only"
        )
    api_key = os.environ.get("AUTH_API_KEY", "")
    if not args.no_port and not api_key:
        raise SetupError("AUTH_API_KEY is not set (needed by the port; or --no-port)")
    queries = _select_queries(args)
    if not queries:
        raise SetupError("no query matches --split / --source")
    run_dir = _run_dir(args)
    snapshot_dir = (
        find_snapshot(run_dir, args.resume)
        if args.resume
        else new_snapshot_dir(run_dir)
    )
    write_meta(
        snapshot_dir,
        {
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "port-only" if args.port_only else "web",
            "web_base_url": None if args.port_only else web_url,
            "api_base_url": None if args.no_port else api_base_url(),
            "queries_file": str(args.queries),
            "query_ids": [q.query_id for q in queries],
        },
    )
    print(f"snapshot {snapshot_dir}", file=sys.stderr)

    def progress(done: int, total: int) -> None:
        print(f"\rqueries {done}/{total}", end="", file=sys.stderr, flush=True)

    async def main() -> int:
        api = (
            None
            if args.no_port
            else SearchAPI(api_base_url(), api_key, max_retries=args.max_retries)
        )
        web = (
            None
            if args.port_only
            else WebClient(web_url, debug_key, max_retries=args.max_retries)
        )
        try:
            if web is None:
                assert api is not None
                summary = await snapshot_port_only(
                    api,
                    queries,
                    snapshot_dir,
                    concurrency=args.concurrency,
                    on_progress=progress,
                )
            else:
                summary = await snapshot_queries(
                    web,
                    api,
                    queries,
                    snapshot_dir,
                    concurrency=args.concurrency,
                    on_progress=progress,
                )
        finally:
            if web is not None:
                await web.aclose()
            if api is not None:
                await api.aclose()
        print(file=sys.stderr)
        calls = "port runs" if args.port_only else "web calls"
        print(
            f"{calls} {summary.called}, already done {summary.skipped}, "
            f"web failed {len(summary.web_failed)}, port failed "
            f"{len(summary.port_failed)}"
        )
        for query_id, error in [
            *summary.web_failed.items(),
            *summary.port_failed.items(),
        ][:5]:
            print(f"  {query_id}: {error}", file=sys.stderr)
        print(f"next: retrieval-eval web-check --run-id {args.run_id}")
        return 1 if summary.web_failed or summary.port_failed else 0

    return asyncio.run(main())


def cmd_web_check(args: argparse.Namespace) -> int:
    from retrieval_eval.pool import RANKINGS_FILE
    from retrieval_eval.web_check import (
        check_snapshot,
        find_snapshot,
        has_drift,
        has_parity_diff,
        output_files,
        summary_lines,
    )

    run_dir = _run_dir(args)
    snapshot_dir = find_snapshot(run_dir, args.snapshot)
    against = find_snapshot(run_dir, args.against) if args.against else None
    lines = check_snapshot(
        snapshot_dir,
        queries_path=args.queries,
        rankings_path=run_dir / RANKINGS_FILE,
        against=against,
    )
    for line in summary_lines(lines):
        print(line)
    print(f"report: {snapshot_dir / output_files(against)[1]}")
    failed = has_drift(lines) if against is not None else has_parity_diff(lines)
    return 1 if failed else 0


# --- label -------------------------------------------------------------------


def _label_setup(args: argparse.Namespace):
    from judge_eval.judge import load_models
    from retrieval_eval.audit import load_key
    from retrieval_eval.data import load_docs, load_queries, load_rankings
    from retrieval_eval.labeller import LabelPromptBook, pairs_from_key, pairs_to_label
    from retrieval_eval.pool import DOCS_FILE, RANKINGS_FILE, build_pool

    run_dir = _run_dir(args)
    prompts = LabelPromptBook(args.prompts_dir, args.prompt_version, args.max_chars)
    available = {m.name: m for m in load_models(args.models)}
    unknown = [name for name in args.model if name not in available]
    if unknown:
        raise SetupError(f"unknown model {unknown}; configured: {sorted(available)}")
    configs = [available[name] for name in dict.fromkeys(args.model)]

    docs = load_docs(run_dir / DOCS_FILE)
    if args.pairs:
        if args.limit_queries:
            raise SetupError("--limit-queries does not apply with --pairs")
        queries = {q.query_id: q for q in load_queries(args.queries)}
        pairs, unusable = pairs_from_key(load_key(args.pairs), queries, docs)
        note = f"{len(unusable)} pairs of {args.pairs.name} cannot be used"
        return configs, prompts, pairs, note

    if not (run_dir / RANKINGS_FILE).exists():
        raise SetupError(f"{run_dir / RANKINGS_FILE} not found: run `pool` first")
    split = None if args.split == "all" else args.split
    queries = load_queries(args.queries, split)
    if args.limit_queries:
        step = max(len(queries) // args.limit_queries, 1)
        queries = queries[::step][: args.limit_queries]
    pool = build_pool(load_rankings(run_dir / RANKINGS_FILE), args.depth)
    pairs, missing = pairs_to_label(queries, pool, docs)
    return configs, prompts, pairs, f"{len(missing)} pooled documents have no snapshot"


def cmd_label(args: argparse.Namespace) -> int:
    from retrieval_eval.labeller import (
        GradeLabeller,
        describe_run,
        estimate_prompt_tokens,
        failures_path,
        label_pairs,
    )

    configs, prompts, pairs, note = _label_setup(args)
    if args.qrels and len(configs) > 1:
        raise SetupError("--qrels names one file: use it with a single --model")
    paths = {
        config.name: args.qrels
        or QRELS_DIR
        / f"llm-{_slug(config.name)}-{prompts.version}-{prompts.sha256[:8]}.jsonl"
        for config in configs
    }
    calls = len(pairs) * len(configs)
    where = "from --pairs" if args.pairs else f"at depth {args.depth}"
    print(f"{len(pairs)} (query, document) pairs {where} ({note})")
    print(
        f"{len(configs)} model(s): up to {calls} calls, about "
        f"{estimate_prompt_tokens(prompts, pairs) * len(configs):,} prompt tokens "
        f"if nothing is labelled yet (documents cut at {prompts.max_chars} characters)"
    )
    for name, path in paths.items():
        print(f"  {name} -> {path}")
    if args.dry_run:
        return 0
    if calls > args.max_pairs:
        raise SetupError(
            f"{calls} calls ({len(pairs)} pairs x {len(configs)} models) exceed "
            f"--max-pairs {args.max_pairs}: narrow the run (--split, --limit-queries, "
            "--depth, fewer --model) or raise the limit on purpose"
        )

    code = 0
    for config in configs:
        qrels_path = paths[config.name]

        def progress(done: int, total: int, name: str = config.name) -> None:
            print(
                f"\r{name}: labelled {done}/{total}",
                end="",
                file=sys.stderr,
                flush=True,
            )

        labeller = GradeLabeller(config, prompts)
        summary = asyncio.run(
            label_pairs(labeller, pairs, qrels_path, on_progress=progress)
        )
        print(file=sys.stderr)
        print(f"{config.name}: {describe_run(summary)}")
        if summary.failures:
            print(f"  failures: {failures_path(qrels_path)}", file=sys.stderr)
        if summary.api_errors:
            code = 1
    return code


def cmd_probe_labellers(args: argparse.Namespace) -> int:
    from judge_eval.judge import load_models
    from retrieval_eval.labeller import LabelPromptBook, probe_labellers

    configs = load_models(args.models)
    if args.only:
        wanted = {name.strip() for name in args.only.split(",")}
        unknown = wanted - {c.name for c in configs}
        if unknown:
            raise SetupError(f"unknown model {sorted(unknown)}")
        configs = [c for c in configs if c.name in wanted]
    prompts = LabelPromptBook(args.prompts_dir, args.prompt_version, args.max_chars)
    probes = asyncio.run(probe_labellers(configs, prompts))
    failed = 0
    for probe in probes:
        g = probe.grading
        if probe.skipped:
            line = f"skipped: {probe.skipped}"
        elif g is not None and g.status == "ok":
            line = (
                f"grade {g.grade} ({g.response_mode}, {g.latency_s:.1f}s, "
                f"{g.completion_tokens} completion tokens)"
            )
        else:
            line = f"{g.status if g else 'failed'}: {g.error if g else ''}"
        failed += not probe.ok
        print(f"{'OK  ' if probe.ok else 'FAIL'} {probe.config.name:48} {line}")
    print("(the built-in pair is clearly relevant: grade 2 expected)")
    return 1 if failed else 0


def cmd_prompt(args: argparse.Namespace) -> int:
    from retrieval_eval.data import load_docs, load_queries
    from retrieval_eval.labeller import LabelPromptBook
    from retrieval_eval.pool import DOCS_FILE

    queries = {q.query_id: q for q in load_queries(args.queries)}
    docs = load_docs(_run_dir(args) / DOCS_FILE)
    if args.query_id not in queries:
        raise SetupError(f"unknown query id {args.query_id!r}")
    if args.doc_id not in docs:
        raise SetupError(f"document {args.doc_id!r} has no snapshot in this run")
    prompts = LabelPromptBook(args.prompts_dir, args.prompt_version, args.max_chars)
    messages, truncated = prompts.render(queries[args.query_id], docs[args.doc_id])
    for message in messages:
        print(f"--- {message['role']} ---\n{message['content']}\n")
    if truncated:
        print(f"(document cut to {args.max_chars} characters)")
    return 0


# --- choosing the labeller ---------------------------------------------------


def _parse_allocation(text: str | None) -> dict[str, int] | None:
    """`consensus-relevant=30,disputed=40,...` -> {stratum: pairs}."""
    if not text:
        return None
    try:
        return {
            name.strip(): int(count)
            for name, count in (part.split("=") for part in text.split(","))
        }
    except ValueError as e:
        raise SetupError(f"--allocation expects name=count,name=count: {e}") from e


def cmd_sample_pairs(args: argparse.Namespace) -> int:
    from retrieval_eval.audit import (
        export_sheet,
        load_key,
        sample_pool_pairs,
        sample_screened_pairs,
        subset_items,
    )
    from retrieval_eval.data import load_docs, load_qrels, load_queries, load_rankings
    from retrieval_eval.pool import DOCS_FILE, RANKINGS_FILE

    run_dir = _run_dir(args)
    queries = {q.query_id: q for q in load_queries(args.queries)}
    docs = load_docs(run_dir / DOCS_FILE)
    if args.subset_of:
        items = subset_items(load_key(args.subset_of), args.n, args.seed)
        stem = "relabel"
    else:
        if args.split is None:
            raise SetupError("--split is required (dev, test or all)")
        split = None if args.split == "all" else args.split
        query_ids = {q.query_id for q in load_queries(args.queries, split)}
        rankings = load_rankings(run_dir / RANKINGS_FILE)
        stem = "selection"
        if args.screeners:
            screeners: dict[str, list] = {}
            for path in args.screeners:
                for qrel in load_qrels(path):
                    screeners.setdefault(qrel.labeller, []).append(qrel)
            sampled = sample_screened_pairs(
                rankings,
                docs,
                screeners,
                query_ids,
                args.depth,
                args.n,
                args.seed,
                allocation=_parse_allocation(args.allocation),
            )
            items = sampled.items
            print(f"screeners: {', '.join(sorted(screeners))}")
            print(f"{'stratum':22} {'pool':>6} {'sampled':>8} {'weight':>8}")
            for name, info in sampled.strata.items():
                print(f"{name:22} {info.pool:>6} {info.sampled:>8} {info.weight:>8.1f}")
            if sampled.unscreened:
                print(f"{sampled.unscreened} pool pairs not graded by every screener")
        else:
            items = sample_pool_pairs(
                rankings,
                docs,
                query_ids,
                args.depth,
                args.n,
                args.seed,
                per_query_cap=args.per_query_cap,
            )
    sheet = args.sheet or LOCAL_DIR / f"{stem}_sheet.csv"
    key = args.key or LOCAL_DIR / f"{stem}_key.json"
    existing = [path for path in (sheet, key) if path.exists()]
    if existing and not args.force:
        raise SetupError(
            f"{existing[0]} exists and may hold human labels: use --force to "
            "overwrite it, or --sheet/--key for other paths"
        )
    written = export_sheet(items, queries, docs, sheet, key)
    in_top = sum(i.in_production_top for i in items)
    print(
        f"{written} rows over {len({i.query_id for i in items})} queries in {sheet} "
        f"({in_top} in production's top 10); key in {key}"
    )
    print("Label the `grade` column (0/1/2) with prompts/<version>/guideline.fr.md.")
    return 0


def cmd_ui_export(args: argparse.Namespace) -> int:
    from retrieval_eval.audit import load_key
    from retrieval_eval.data import load_docs, load_queries
    from retrieval_eval.labelling_ui import build_labelling_html
    from retrieval_eval.pool import DOCS_FILE

    queries = {q.query_id: q for q in load_queries(args.queries)}
    docs = load_docs(_run_dir(args) / DOCS_FILE)
    guideline = (args.prompts_dir / args.prompt_version / "guideline.fr.md").read_text(
        encoding="utf-8"
    )
    html, kept = build_labelling_html(
        load_key(args.key), queries, docs, guideline, args.title
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(
        f"{len(kept)} pairs in {args.out} ({args.out.stat().st_size / 1e6:.1f} MB). "
        "Open it in a browser; labels autosave there, then use `Export CSV`."
    )
    print(
        "Then: retrieval-eval audit-import --sheet <exported csv> "
        f"--key {args.key} --annotator <name>"
    )
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    from retrieval_eval.data import load_qrels
    from retrieval_eval.jsonl import read_jsonl
    from retrieval_eval.labeller import LabelFailure, failures_path
    from retrieval_eval.report import compare_labellers, render_compare

    human = load_qrels(*args.human)
    names = sorted({q.labeller for q in human})
    reference = args.human_labeller
    if reference is None:
        if len(names) != 1:
            raise SetupError(f"human files hold {names}: choose with --human-labeller")
        reference = names[0]
    human = [q for q in human if q.labeller == reference]

    models: dict[str, list] = {}
    failures: dict[str, list] = {}
    for path in args.models_qrels:
        qrels = load_qrels(path)
        failed = list(read_jsonl(failures_path(path), LabelFailure))
        for labeller in sorted(
            {q.labeller for q in qrels} | {f.labeller for f in failed}
        ):
            name = labeller if labeller not in models else f"{labeller} [{path.stem}]"
            models[name] = [q for q in qrels if q.labeller == labeller]
            failures[name] = [f for f in failed if f.labeller == labeller]
    if not models:
        raise SetupError("no model labels found in --models-qrels")

    weights = None
    if args.key:
        from retrieval_eval.audit import load_key

        weights = {
            (i.query_id, i.doc_id, i.text_sha256): i.weight for i in load_key(args.key)
        }
    result = compare_labellers(
        human,
        models,
        failures,
        n_boot=args.bootstrap,
        seed=args.seed,
        bar=(args.bar_useful, args.bar_direct),
        weights=weights,
    )
    text = render_compare(result, args.bootstrap)
    run_dir = _run_dir(args)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "compare.md").write_text(text, encoding="utf-8")
    result.table.to_csv(run_dir / "compare.csv", index=False)
    print(text)
    print(f"Wrote compare.md and compare.csv to {run_dir}")
    return 0


# --- audit and agreement -----------------------------------------------------


def cmd_audit_export(args: argparse.Namespace) -> int:
    from retrieval_eval.audit import export_sheet, sample_audit
    from retrieval_eval.data import load_docs, load_qrels, load_queries, load_rankings
    from retrieval_eval.pool import DOCS_FILE, RANKINGS_FILE

    run_dir = _run_dir(args)
    split = None if args.split == "all" else args.split
    queries = {q.query_id: q for q in load_queries(args.queries, split)}
    qrels = [
        q
        for q in load_qrels(*args.llm_qrels)
        if q.labeller.startswith("llm:") and q.query_id in queries
    ]
    if not qrels:
        raise SetupError("no LLM labels for these queries: run `label` first")
    items = sample_audit(
        qrels,
        load_rankings(run_dir / RANKINGS_FILE),
        args.n,
        args.seed,
        per_query_cap=args.per_query_cap,
    )
    written = export_sheet(
        items,
        queries,
        load_docs(run_dir / DOCS_FILE),
        args.sheet,
        args.key,
    )
    print(f"{written} rows in {args.sheet} (blind: no LLM grade); key in {args.key}")
    print("Give the annotator the sheet and prompts/<version>/guideline.fr.md only.")
    return 0


def cmd_audit_import(args: argparse.Namespace) -> int:
    from retrieval_eval.audit import import_sheet
    from retrieval_eval.jsonl import append_jsonl

    qrels, blank = import_sheet(
        args.sheet, args.key, args.annotator, args.guideline_version
    )
    out = args.out or QRELS_DIR / f"human-{_slug(args.annotator)}.jsonl"
    append_jsonl(out, qrels)
    print(f"{len(qrels)} human labels appended to {out} ({blank} blank rows skipped)")
    return 0


def cmd_agreement(args: argparse.Namespace) -> int:
    from retrieval_eval.data import load_qrels
    from retrieval_eval.report import agreement_table, render_agreement

    def of(paths: list[Path], labeller: str | None):
        qrels = load_qrels(*paths)
        names = sorted({q.labeller for q in qrels})
        if labeller is None and len(names) > 1:
            raise SetupError(
                f"{paths} hold several labellers {names}: pass --*-labeller"
            )
        return [q for q in qrels if labeller in (None, q.labeller)], (
            labeller or names[0]
        )

    reference, reference_name = of(args.reference, args.reference_labeller)
    other, other_name = of(args.other, args.other_labeller)
    table, confusion = agreement_table(
        reference, other, n_boot=args.bootstrap, seed=args.seed
    )
    text = render_agreement(table, confusion, reference_name, other_name)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    return 0


# --- report ------------------------------------------------------------------


def cmd_export_dataset(args: argparse.Namespace) -> int:
    import hashlib
    from collections import Counter

    from retrieval_eval.data import load_docs, load_qrels, load_queries, load_rankings
    from retrieval_eval.dataset_export import (
        DatasetError,
        build_pairs,
        render_data_card,
        write_dataset,
    )
    from retrieval_eval.labeller import LabelPromptBook
    from retrieval_eval.labelling_ui import grade_names
    from retrieval_eval.pool import DOCS_FILE, RANKINGS_FILE
    from retrieval_eval.report import labeller_profile

    run_dir = _run_dir(args)
    qrels = load_qrels(*args.qrels)
    labellers = sorted({q.labeller for q in qrels})
    labeller = args.labeller or (labellers[0] if len(labellers) == 1 else None)
    if labeller is None or labeller not in labellers:
        raise SetupError(f"choose the labeller with --labeller among {labellers}")
    queries = {q.query_id: q for q in load_queries(args.queries)}
    human = None
    if args.human:
        human_all = load_qrels(*args.human)
        names = sorted({q.labeller for q in human_all})
        reference = args.human_labeller or (names[0] if len(names) == 1 else None)
        if reference is None or reference not in names:
            raise SetupError(f"choose the human with --human-labeller among {names}")
        human = [q for q in human_all if q.labeller == reference]

    dataset = build_pairs(
        load_rankings(run_dir / RANKINGS_FILE),
        queries,
        load_docs(run_dir / DOCS_FILE),
        qrels,
        labeller,
        args.depth,
        human,
    )
    prompts = LabelPromptBook(args.prompts_dir, args.prompt_version, args.max_chars)
    shas = {r["prompt_sha256"] for r in dataset.pairs}
    if shas != {prompts.sha256}:
        raise DatasetError(
            f"the labels were made with prompt hashes {sorted(shas)}, not "
            f"{prompts.sha256} (prompt files + --max-chars {args.max_chars}): pass "
            "the --prompt-version and --max-chars they were made with"
        )

    profile = None
    if human is not None:
        weights = None
        if args.key:
            from retrieval_eval.audit import load_key

            weights = {
                (i.query_id, i.doc_id, i.text_sha256): i.weight
                for i in load_key(args.key)
            }
        profile = labeller_profile(
            human,
            [q for q in qrels if q.labeller == labeller],
            weights=weights,
            n_boot=args.bootstrap,
            seed=args.seed,
        )
    guideline = args.prompts_dir / args.prompt_version / "guideline.fr.md"
    served = Counter(
        q.served_model for q in qrels if q.labeller == labeller and q.served_model
    )
    card = render_data_card(
        dataset,
        labeller,
        served.most_common(1)[0][0] if served else None,
        args.prompt_version,
        prompts.sha256,
        args.max_chars,
        hashlib.sha256(guideline.read_bytes()).hexdigest()[:12],
        args.depth,
        profile,
        human[0].labeller if human else None,
        grade_names(guideline.read_text(encoding="utf-8")),
    )
    write_dataset(args.out, dataset, card)
    print(
        f"{len(dataset.pairs)} pairs, {len(dataset.queries)} queries, "
        f"{len(dataset.documents)} documents written to {args.out} (local: contains "
        "anonymised real questions, do not commit without review)"
    )
    return 0


def cmd_query_report(args: argparse.Namespace) -> int:
    from retrieval_eval.data import (
        grades_by_query,
        load_docs,
        load_qrels,
        load_queries,
        load_rankings,
    )
    from retrieval_eval.pool import DOCS_FILE, RANKINGS_FILE
    from retrieval_eval.query_report import (
        find_queries,
        render_query_report,
        render_weaknesses,
        worst_queries,
    )

    run_dir = _run_dir(args)
    qrels = load_qrels(*args.qrels)
    labellers = sorted({q.labeller for q in qrels})
    labeller = args.labeller or (labellers[0] if len(labellers) == 1 else None)
    if labeller is None or labeller not in labellers:
        raise SetupError(f"choose the labeller with --labeller among {labellers}")
    docs = load_docs(run_dir / DOCS_FILE)
    current = [
        q
        for q in qrels
        if q.labeller == labeller
        and q.doc_id in docs
        and docs[q.doc_id].text_sha256 == q.text_sha256
    ]
    grades = grades_by_query(current, labeller)
    queries = {q.query_id: q for q in load_queries(args.queries)}
    rankings = load_rankings(run_dir / RANKINGS_FILE)

    if args.worst:
        text = render_weaknesses(worst_queries(rankings, grades, args.worst), queries)
    else:
        if not (args.query_id or args.search):
            raise SetupError("give --query-id, --search or --worst N")
        matches = find_queries(list(queries.values()), args.query_id or args.search)
        if args.query_id:
            matches = [q for q in matches if q.query_id == args.query_id] or matches
        if not matches:
            raise SetupError(f"no question matches {args.query_id or args.search!r}")
        if len(matches) > 1:
            listing = "\n".join(
                f"  {q.query_id}  {' '.join(q.text.split())[:90]}" for q in matches[:15]
            )
            raise SetupError(
                f"{len(matches)} questions match, pass --query-id:\n{listing}"
            )
        query = matches[0]
        if not grades.get(query.query_id):
            raise SetupError(f"question {query.query_id} has no grade from {labeller}")
        human = None
        if args.human:
            human_all = load_qrels(*args.human)
            names = sorted({q.labeller for q in human_all})
            reference = args.human_labeller or (names[0] if len(names) == 1 else None)
            if reference is None or reference not in names:
                raise SetupError(
                    f"choose the human with --human-labeller among {names}"
                )
            human = grades_by_query(
                [q for q in human_all if q.labeller == reference], reference
            ).get(query.query_id, {})
        rationales = {
            q.doc_id: q.rationale for q in current if q.query_id == query.query_id
        }
        text = render_query_report(
            query,
            rankings,
            docs,
            grades[query.query_id],
            rationales,
            human or None,
            rationale_chars=args.rationale_chars,
        )
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"\nWritten to {args.out}", file=sys.stderr)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from retrieval_eval.data import (
        dataset_sha256,
        grades_by_query,
        load_docs,
        load_qrels,
        load_queries,
        load_rankings,
    )
    from retrieval_eval.pool import CONFIG_FILE, DOCS_FILE, RANKINGS_FILE
    from retrieval_eval.report import (
        build_report,
        labeller_profile,
        render_markdown,
        render_profile,
    )

    run_dir = _run_dir(args)
    qrels = load_qrels(*args.qrels)
    labellers = sorted({q.labeller for q in qrels})
    labeller = args.labeller
    if labeller is None:
        if len(labellers) != 1:
            raise SetupError(
                f"several labellers {labellers}: choose one with --labeller"
            )
        labeller = labellers[0]
    elif labeller not in labellers:
        raise SetupError(f"labeller {labeller!r} not in the qrels; found {labellers}")

    # Labels given for another text of a document do not apply to the snapshot.
    docs = load_docs(run_dir / DOCS_FILE)
    current = [
        q
        for q in qrels
        if q.doc_id in docs and docs[q.doc_id].text_sha256 == q.text_sha256
    ]
    stale = sum(q.labeller == labeller for q in qrels) - sum(
        q.labeller == labeller for q in current
    )
    queries = {q.query_id: q for q in load_queries(args.queries)}
    report = build_report(
        load_rankings(run_dir / RANKINGS_FILE),
        queries,
        grades_by_query(current, labeller),
        ks=args.ks,
        n_boot=args.bootstrap,
        seed=args.seed,
    )

    context = {
        "run": args.run_id,
        "labeller": labeller,
        "queries file sha256": dataset_sha256(args.queries)[:12],
        "labels": (
            f"{sum(q.labeller == labeller for q in current)} usable, "
            f"{stale} stale (document text changed)"
        ),
    }
    config = run_dir / CONFIG_FILE
    if config.exists() and dataset_sha256(args.queries) not in config.read_text():
        print(
            "warning: queries.jsonl changed since this run was pooled", file=sys.stderr
        )
    text = render_markdown(report, args.bootstrap, context)
    profile = None
    if args.human:
        human = load_qrels(*args.human)
        human_names = sorted({q.labeller for q in human})
        reference = args.human_labeller
        if reference is None:
            if len(human_names) != 1:
                raise SetupError(
                    f"human files hold {human_names}: choose with --human-labeller"
                )
            reference = human_names[0]
        weights = None
        if args.key:
            from retrieval_eval.audit import load_key

            weights = {
                (i.query_id, i.doc_id, i.text_sha256): i.weight
                for i in load_key(args.key)
            }
        profile = labeller_profile(
            [q for q in human if q.labeller == reference],
            [q for q in current if q.labeller == labeller],
            weights=weights,
            n_boot=args.bootstrap,
            seed=args.seed,
        )
        text += "\n" + render_profile(profile, labeller, reference)
    (run_dir / "report.md").write_text(text, encoding="utf-8")
    if profile is not None:
        profile.table.to_csv(run_dir / "labeller_profile.csv", index=False)
    report.metrics.to_csv(run_dir / "metrics.csv", index=False)
    report.pairwise.to_csv(run_dir / "pairwise.csv", index=False)
    report.per_query.to_csv(run_dir / "per_query.csv", index=False)
    print(text)
    print(f"Wrote report.md and CSVs to {run_dir}")
    return 0


# --- parser ------------------------------------------------------------------


def _common(sub: argparse.ArgumentParser, run: bool = True) -> None:
    sub.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    if run:
        sub.add_argument("--run-id", required=True, help="directory under --runs-dir")
        sub.add_argument("--runs-dir", type=Path, default=ROOT / "runs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retrieval-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sample = sub.add_parser(
        "sample-queries",
        help="Sample real user questions from a Metabase export, anonymise them",
    )
    sample.add_argument("--csv", type=Path, required=True, help="Metabase export")
    sample.add_argument("--n", type=int, default=300, help="Real questions to keep")
    sample.add_argument("--seed", type=int, default=20260212)
    sample.add_argument("--user-cap", type=int, default=5)
    sample.add_argument(
        "--dev-size",
        type=int,
        default=60,
        help="Queries in the dev split (labeller tuning); the rest is test",
    )
    sample.add_argument("--golden", type=Path, default=ROOT / "dataset/18q_human.json")
    sample.add_argument("--out", type=Path, default=DEFAULT_QUERIES)
    sample.add_argument("--audit", type=Path, default=LOCAL_DIR / "selection_audit.csv")
    sample.add_argument("--force", action="store_true", help="Overwrite --out")
    sample.set_defaults(func=cmd_sample_queries)

    add = sub.add_parser(
        "add-queries",
        help="Append questions from a JSON file to queries.jsonl (splits stay fixed)",
    )
    add.add_argument("--file", type=Path, required=True, help="JSON list of rows")
    add.add_argument("--source", required=True, help="Value of the `source` field")
    add.add_argument("--seed", type=int, default=20260212)
    add.add_argument("--out", type=Path, default=DEFAULT_QUERIES)
    add.add_argument("--audit", type=Path, default=LOCAL_DIR / "selection_audit.csv")
    add.add_argument("--dry-run", action="store_true", help="Report, write nothing")
    add.set_defaults(func=cmd_add_queries)

    pool = sub.add_parser(
        "pool",
        help="Run the retrieval variants (needs the API: AUTH_API_KEY, API_BASE_URL)",
    )
    _common(pool)
    pool.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    pool.add_argument("--limit", type=int, help="Queries, spread over the file")
    pool.add_argument(
        "--variants",
        nargs="+",
        default=["knn", "hybrid", "hybrid+rerank"],
        help="Retrieval variants to run",
    )
    pool.add_argument("--top-k", type=int, default=200, help="Chunks per search")
    pool.add_argument(
        "--depth",
        type=int,
        default=20,
        help="Documents per variant to fetch the text of",
    )
    pool.add_argument("--concurrency", type=int, default=4)
    pool.add_argument("--max-retries", type=int, default=3)
    pool.set_defaults(func=cmd_pool)

    web_snapshot = sub.add_parser(
        "web-snapshot",
        help="Call the web /api/generate and the port, save both (needs "
        "WEB_BASE_URL, DEBUG_API_KEY, AUTH_API_KEY; runs LLM generations)",
    )
    _common(web_snapshot)
    web_snapshot.add_argument("--split", choices=["dev", "test", "all"], default="all")
    web_snapshot.add_argument("--source", help="Only queries of this source (idcc22)")
    web_snapshot.add_argument("--limit", type=int, help="Queries, spread over the file")
    web_snapshot.add_argument(
        "--no-port", action="store_true", help="Web calls only, no port ranking"
    )
    web_snapshot.add_argument(
        "--port-only",
        action="store_true",
        help="No web call: the API's /anonymize then the port, as `pool` (no LLM)",
    )
    web_snapshot.add_argument(
        "--resume",
        metavar="SNAPSHOT",
        help="Complete this snapshot instead of a new one",
    )
    web_snapshot.add_argument("--concurrency", type=int, default=2)
    web_snapshot.add_argument("--max-retries", type=int, default=1)
    web_snapshot.set_defaults(func=cmd_web_snapshot)

    web_check = sub.add_parser(
        "web-check",
        help="Compare a web snapshot with the stored run or another snapshot (no call)",
    )
    _common(web_check)
    web_check.add_argument("--snapshot", help="Snapshot folder name (default: latest)")
    web_check.add_argument(
        "--against", metavar="SNAPSHOT", help="Compare with this earlier snapshot"
    )
    web_check.set_defaults(func=cmd_web_check)

    for name, helptext in (
        ("label", "LLM-grade the pooled documents (calls a chat model)"),
        ("prompt", "Print the exact labelling prompt for one query and document"),
    ):
        sub_parser = sub.add_parser(name, help=helptext)
        _common(sub_parser)
        sub_parser.add_argument("--prompt-version", default="v1")
        sub_parser.add_argument("--prompts-dir", type=Path, default=PROMPTS_DIR)
        sub_parser.add_argument(
            "--max-chars", type=int, default=12000, help="Document length sent"
        )
        if name == "label":
            sub_parser.add_argument("--models", type=Path, default=LABELLERS_CONFIG)
            sub_parser.add_argument(
                "--model",
                action="append",
                required=True,
                help="Name in the models file; repeat to run several, one after "
                "the other",
            )
            sub_parser.add_argument(
                "--pairs",
                type=Path,
                help="Key file of `sample-pairs`: label exactly these pairs (then "
                "--split and --depth are not used)",
            )
            sub_parser.add_argument(
                "--split", choices=["dev", "test", "all"], default="dev"
            )
            sub_parser.add_argument("--limit-queries", type=int)
            sub_parser.add_argument(
                "--depth", type=int, default=10, help="Documents per variant to label"
            )
            sub_parser.add_argument("--qrels", type=Path, help="Output labels file")
            sub_parser.add_argument(
                "--max-pairs",
                type=int,
                default=500,
                help="Refuse a run with more calls (pairs x models): cost guard",
            )
            sub_parser.add_argument(
                "--dry-run", action="store_true", help="Print the size of the run only"
            )
            sub_parser.set_defaults(func=cmd_label)
        else:
            sub_parser.add_argument("--query-id", required=True)
            sub_parser.add_argument("--doc-id", required=True)
            sub_parser.set_defaults(func=cmd_prompt)

    sample_pairs = sub.add_parser(
        "sample-pairs",
        help="Blind sheet of pooled pairs, drawn with no model, to compare labellers",
    )
    _common(sample_pairs)
    sample_pairs.add_argument("--split", choices=["dev", "test", "all"])
    sample_pairs.add_argument("--depth", type=int, default=10)
    sample_pairs.add_argument("--n", type=int, default=120)
    sample_pairs.add_argument("--seed", type=int, default=0)
    sample_pairs.add_argument("--per-query-cap", type=int, default=3)
    sample_pairs.add_argument(
        "--screeners",
        type=Path,
        nargs="+",
        help="Qrels files of the screener models (graded over the whole pool): draw "
        "by strata of their grades instead of by provenance, each pair carrying "
        "the weight of its stratum (--per-query-cap does not apply)",
    )
    sample_pairs.add_argument(
        "--allocation",
        help="With --screeners: pairs per stratum, e.g. consensus-relevant=30,"
        "consensus-partial=20,disputed=40,consensus-irrelevant=30 (default: shares "
        "of --n)",
    )
    sample_pairs.add_argument(
        "--subset-of",
        type=Path,
        help="Key file: redraw --n of its pairs under fresh ids (second blind pass)",
    )
    sample_pairs.add_argument("--sheet", type=Path)
    sample_pairs.add_argument("--key", type=Path)
    sample_pairs.add_argument(
        "--force", action="store_true", help="Overwrite an existing sheet or key"
    )
    sample_pairs.set_defaults(func=cmd_sample_pairs)

    ui = sub.add_parser(
        "ui-export",
        help="One local HTML page to label a sampling key (autosave, CSV export)",
    )
    _common(ui)
    ui.add_argument("--key", type=Path, default=LOCAL_DIR / "selection_key.json")
    ui.add_argument("--out", type=Path, default=LOCAL_DIR / "labelling.html")
    ui.add_argument("--title", default="Relevance labelling")
    ui.add_argument("--prompt-version", default="v1")
    ui.add_argument("--prompts-dir", type=Path, default=PROMPTS_DIR)
    ui.set_defaults(func=cmd_ui_export)

    probe = sub.add_parser(
        "probe-labellers",
        help="One real labelling call per candidate model (checks keys, JSON mode)",
    )
    probe.add_argument("--models", type=Path, default=LABELLERS_CONFIG)
    probe.add_argument("--only", help="Comma-separated model names")
    probe.add_argument("--prompt-version", default="v1")
    probe.add_argument("--prompts-dir", type=Path, default=PROMPTS_DIR)
    probe.add_argument("--max-chars", type=int, default=12000)
    probe.set_defaults(func=cmd_probe_labellers)

    compare = sub.add_parser(
        "compare",
        help="Compare candidate labellers against one human on the same pairs",
    )
    compare.add_argument("--run-id", required=True, help="where compare.md is written")
    compare.add_argument("--runs-dir", type=Path, default=ROOT / "runs")
    compare.add_argument("--human", type=Path, nargs="+", required=True)
    compare.add_argument("--human-labeller")
    compare.add_argument(
        "--models-qrels", type=Path, nargs="+", required=True, help="one file per model"
    )
    compare.add_argument(
        "--key",
        type=Path,
        help="Sampling key with weights (from `sample-pairs --screeners`): the kappas "
        "then estimate the pool's; only the pairs of the key are used",
    )
    compare.add_argument("--bar-useful", type=float, default=0.6)
    compare.add_argument("--bar-direct", type=float, default=0.5)
    compare.add_argument("--bootstrap", type=int, default=1000)
    compare.add_argument("--seed", type=int, default=0)
    compare.set_defaults(func=cmd_compare)

    export = sub.add_parser(
        "audit-export", help="Blind sheet for a human to label a sample of LLM labels"
    )
    _common(export)
    export.add_argument("--llm-qrels", type=Path, nargs="+", required=True)
    export.add_argument("--split", choices=["dev", "test", "all"], default="test")
    export.add_argument("--n", type=int, default=150)
    export.add_argument("--seed", type=int, default=0)
    export.add_argument("--per-query-cap", type=int, default=3)
    export.add_argument("--sheet", type=Path, default=LOCAL_DIR / "audit_sheet.csv")
    export.add_argument("--key", type=Path, default=LOCAL_DIR / "audit_key.json")
    export.set_defaults(func=cmd_audit_export)

    imp = sub.add_parser("audit-import", help="Human labels from a filled sheet")
    imp.add_argument("--sheet", type=Path, required=True)
    imp.add_argument("--key", type=Path, default=LOCAL_DIR / "audit_key.json")
    imp.add_argument("--annotator", required=True)
    imp.add_argument("--guideline-version", default="v1")
    imp.add_argument("--out", type=Path)
    imp.set_defaults(func=cmd_audit_import)

    agree = sub.add_parser(
        "agreement", help="Agreement of the LLM labels with the human ones"
    )
    agree.add_argument(
        "--reference", type=Path, nargs="+", required=True, help="e.g. human"
    )
    agree.add_argument("--other", type=Path, nargs="+", required=True, help="e.g. LLM")
    agree.add_argument("--reference-labeller")
    agree.add_argument("--other-labeller")
    agree.add_argument("--bootstrap", type=int, default=1000)
    agree.add_argument("--seed", type=int, default=0)
    agree.add_argument("--out", type=Path)
    agree.set_defaults(func=cmd_agreement)

    export_ds = sub.add_parser(
        "export-dataset",
        help="Write the labelled pairs, queries, documents and a data card",
    )
    _common(export_ds)
    export_ds.add_argument("--qrels", type=Path, nargs="+", required=True)
    export_ds.add_argument(
        "--labeller", help="e.g. llm:scaleway/llama-3.3-70b-instruct"
    )
    export_ds.add_argument("--depth", type=int, default=20)
    export_ds.add_argument("--prompt-version", default="v1")
    export_ds.add_argument("--prompts-dir", type=Path, default=PROMPTS_DIR)
    export_ds.add_argument(
        "--max-chars",
        type=int,
        default=120000,
        help="Document length limit the labels were made with (checked)",
    )
    export_ds.add_argument(
        "--human",
        type=Path,
        nargs="+",
        help="Human qrels: mark the gold pairs and add the labeller's error profile "
        "to the data card",
    )
    export_ds.add_argument("--human-labeller")
    export_ds.add_argument(
        "--key", type=Path, help="Sampling key (weights) for --human"
    )
    export_ds.add_argument("--bootstrap", type=int, default=1000)
    export_ds.add_argument("--seed", type=int, default=0)
    export_ds.add_argument("--out", type=Path, default=ROOT / "retrieval/dataset")
    export_ds.set_defaults(func=cmd_export_dataset)

    qr = sub.add_parser(
        "query-report",
        help="One question: what each variant returned, the grades, what was missed",
    )
    _common(qr)
    qr.add_argument("--qrels", type=Path, nargs="+", required=True)
    qr.add_argument("--labeller")
    target = qr.add_mutually_exclusive_group()
    target.add_argument("--query-id", help="Query id (or a prefix of it)")
    target.add_argument("--search", help="Words of the question (accents/case ignored)")
    target.add_argument(
        "--worst", type=int, help="List the N questions where production scores lowest"
    )
    qr.add_argument("--human", type=Path, nargs="+", help="Also show your grades")
    qr.add_argument("--human-labeller")
    qr.add_argument("--rationale-chars", type=int, default=200)
    qr.add_argument("--out", type=Path, help="Also write the report to this file")
    qr.set_defaults(func=cmd_query_report)

    report = sub.add_parser(
        "report", help="Retrieval metrics with confidence intervals"
    )
    _common(report)
    report.add_argument("--qrels", type=Path, nargs="+", required=True)
    report.add_argument("--labeller", help="e.g. llm:albert/gpt-oss-120b")
    report.add_argument(
        "--human",
        type=Path,
        nargs="+",
        help="Human qrels: append the labeller's error profile against them",
    )
    report.add_argument("--human-labeller")
    report.add_argument(
        "--key",
        type=Path,
        help="With --human: sampling key whose weights make the profile a pool "
        "estimate (only its pairs are used)",
    )
    report.add_argument("--ks", type=int, nargs="+", default=[5, 10, 20])
    report.add_argument("--bootstrap", type=int, default=1000)
    report.add_argument("--seed", type=int, default=0)
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    from retrieval_eval.audit import AuditError
    from retrieval_eval.pool import PoolConfigError
    from retrieval_eval.search_client import SearchAPIError

    load_dotenv(ROOT / ".env")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (
        SetupError,
        AuditError,
        PoolConfigError,
        SearchAPIError,
        FileNotFoundError,
        RuntimeError,
        ValueError,
    ) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
