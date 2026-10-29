import json
import logging
from pathlib import Path
from typing import Annotated

import typer

from ingestion.config import DATASETS, load_config
from ingestion.contract import SCHEMA_MAJOR, json_schema
from ingestion.settings import Settings, secret

app = typer.Typer(no_args_is_help=True, help="Build the search index.")

PROJECT_DIR = Path(__file__).resolve().parents[2]
SCHEMA_FILE = PROJECT_DIR / "schema" / f"chunk.v{SCHEMA_MAJOR}.schema.json"

StoreOption = Annotated[
    str | None,
    typer.Option(help="Snapshot store: s3 or local (default: SNAPSHOT_STORE)"),
]


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # quieten the HTTP clients
    for name in ("httpx", "opensearch", "botocore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


@app.command()
def index(
    config: Annotated[Path, typer.Option(help="Config file")] = Path(
        "config/local.toml"
    ),
    only: Annotated[
        str | None,
        typer.Option(help="Comma-separated subset of the include list"),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option(help="Chunk only: no embedding, no write")
    ] = False,
    dump: Annotated[
        Path | None, typer.Option(help="Write the chunks (one JSONL per source)")
    ] = None,
    store: StoreOption = None,
):
    """Chunk, embed and index the sources of the include list."""
    from ingestion.embed import AlbertEmbedder
    from ingestion.index_writer import SearchIndexWriter
    from ingestion.pipeline import Inputs, run
    from ingestion.snapshots.store import make_store

    settings = Settings()
    cfg = load_config(config)
    result = run(
        cfg,
        Inputs(store=make_store(settings, store), config=cfg, settings=settings),
        only=only.split(",") if only else None,
        dry_run=dry_run,
        dump=dump,
        writer_factory=lambda: SearchIndexWriter(settings),
        embedder_factory=lambda: AlbertEmbedder(settings, cfg.embedding.dim),
    )
    typer.echo(json.dumps({"counts": result.counts, "index": result.index}))


@app.command()
def fetch(
    datasets: Annotated[
        list[str], typer.Argument(help=f"Datasets to fetch: {', '.join(DATASETS)}")
    ],
    store: StoreOption = None,
    from_dir: Annotated[
        Path | None,
        typer.Option(
            help="Import this directory instead of downloading: the data/ directory "
            "of a legi-data or kali-data checkout, or Judilibre year files "
            "(one dataset only)"
        ),
    ] = None,
    since_year: Annotated[
        int | None,
        typer.Option(
            help="judilibre: download again from this year, carry the earlier "
            "years over from the latest snapshot (default: last year)"
        ),
    ] = None,
    full: Annotated[
        bool, typer.Option(help="judilibre: download every year again")
    ] = False,
    allow_shrink: Annotated[
        bool,
        typer.Option(
            help="judilibre: accept a year with far fewer decisions than in the "
            "latest snapshot"
        ),
    ] = False,
):
    """Snapshot the latest upstream data (npm packages, Judilibre API)."""
    from ingestion.snapshots.fetch import (
        fetch_judilibre,
        fetch_npm,
        import_dir,
    )
    from ingestion.snapshots.store import make_store
    from ingestion.sources.judilibre import JudilibreClient

    unknown = [d for d in datasets if d not in DATASETS]
    if unknown:
        raise typer.BadParameter(f"Unknown datasets: {', '.join(unknown)}")
    if from_dir and len(datasets) != 1:
        raise typer.BadParameter("--from-dir takes a single dataset")
    if (since_year is not None or full or allow_shrink) and (
        datasets != ["judilibre"] or from_dir
    ):
        raise typer.BadParameter(
            "--since-year, --full and --allow-shrink only apply to downloading "
            "judilibre"
        )
    if full and since_year is not None:
        raise typer.BadParameter("--full and --since-year are exclusive")
    settings = Settings()
    snapshot_store = make_store(settings, store)
    for dataset in datasets:
        if from_dir:
            manifest = import_dir(snapshot_store, dataset, from_dir)
        elif dataset == "judilibre":
            settings.require("judilibre_api_key")
            client = JudilibreClient(secret(settings.judilibre_api_key))
            manifest = fetch_judilibre(
                snapshot_store,
                client,
                since_year=since_year,
                full=full,
                allow_shrink=allow_shrink,
            )
        else:
            manifest = fetch_npm(snapshot_store, dataset)
        typer.echo(
            f"{dataset}: "
            + (f"stored {manifest.snapshot_id}" if manifest else "up to date")
        )


@app.command()
def schema(
    check: Annotated[
        bool, typer.Option(help="Fail if the committed schema is out of date")
    ] = False,
):
    """Write the JSON schema of the stored chunks."""
    content = json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"
    if check:
        if not SCHEMA_FILE.exists() or SCHEMA_FILE.read_text() != content:
            typer.echo(f"{SCHEMA_FILE} is out of date: run ingest schema")
            raise typer.Exit(code=1)
        typer.echo(f"{SCHEMA_FILE.name} is up to date")
        return
    SCHEMA_FILE.parent.mkdir(exist_ok=True)
    SCHEMA_FILE.write_text(content)
    typer.echo(f"Wrote {SCHEMA_FILE}")
