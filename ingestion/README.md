# Ingestion

Builds the search index that the api searches (alias `chunks`), on OpenSearch or Elasticsearch.

Inputs:
- raw source **snapshots** on S3: the code du travail (LEGI), collective agreements (KALI), Cour de cassation decisions (Judilibre)
- the CDTN database (contributions, fiches, information pages), read directly

Output: one document per chunk, in the format published in [`schema/chunk.v1.schema.json`](schema/chunk.v1.schema.json).

## Setup

```sh
cd ingestion
cp .env.example .env   # search index, Albert, Postgres, Judilibre and S3 settings
uv sync
```

### Search engine

`SEARCH_ENGINE` selects the engine, `opensearch` (default) or `elasticsearch`. The api reads the same variables, so set both to the same engine.

| | `SEARCH_ENGINE` | `SEARCH_HOSTNAME` (local) |
|---|---|---|
| OpenSearch | `opensearch` | `http://localhost:9201` (`docker compose up -d opensearch`) |
| Elasticsearch 8 | `elasticsearch` | `http://localhost:9202` (`docker compose --profile elasticsearch up -d elasticsearch`) |

`SEARCH_CREDENTIALS` is `user:password`, or the base64 token of it. `ELASTIC_API_KEY` still works as the former name of `SEARCH_CREDENTIALS`. `SEARCH_INDEX` (default `chunks`) is the alias to publish: it is an environment variable, shared with the api, which reads the same one. The index is built with the engine's own vector mapping, so switching engine means running `ingest index` again.

## 1. Snapshot the raw sources: `ingest fetch`

```sh
uv run ingest fetch legi                    # latest @socialgouv/legi-data (npm)
uv run ingest fetch judilibre               # PISTE API, see below
uv run ingest fetch kali --from-dir ../../kali-data/data
```

Each run writes an immutable snapshot, then points `LATEST` to it:

```
{S3_PREFIX}{legi|kali|judilibre}/{snapshot_id}/manifest.json   # files with sha256, upstream version
{S3_PREFIX}{legi|kali|judilibre}/{snapshot_id}/<files>
{S3_PREFIX}{legi|kali|judilibre}/LATEST.json
```

Snapshot ids:
- npm packages: the package version, e.g. `2.575.0`.
- Imported directories: the package version plus a content hash, e.g. `3.473.0-local.0429ef96`.
- Judilibre: the UTC date.

A fetch with nothing new does nothing.

### Judilibre

```sh
uv run ingest fetch judilibre                          # first run: every year since 1990 (about 5 min)
uv run ingest fetch judilibre                          # later runs: last year and this year (about 25 s)
uv run ingest fetch judilibre --since-year 2023        # re-download from 2023
uv run ingest fetch judilibre --full                   # re-download every year
uv run ingest fetch judilibre --from-dir path/to/years # import local <year>.json files, no API call
```

- **Window refresh.** Bulletin publications and summary edits land on past years, so a refresh re-downloads last year and this year, and carries the earlier years over from the latest snapshot. Run `--full` now and then (monthly) to catch deletions and late edits.
- **Nothing changed, nothing stored.** Files are sorted and deduplicated, so unchanged data gives identical files. The refresh then publishes no new snapshot and `LATEST` stays put.
- **Shrink guard.** A downloaded year with under 90% of the decisions of the latest snapshot is refused. Pass `--allow-shrink` when that is expected.
- **Complete years.** The API's pagination is unreliable: walking the pages of a year repeated one decision and skipped another. Each query is therefore sized from the API's `total`: a window that fits one page is read in a single request, a bigger one is split in two, and every window is checked against its `total`.

**KALI comes from a local directory.** The published `@socialgouv/kali-data` (npm and GitHub) has most agreements empty: 343 of 393 in 3.514.0. Regenerate a kali-data checkout with its own fetch script, then import its `data/` directory. The manifest records how many agreements are still empty.

`SNAPSHOT_STORE=local` (or `--store local`) uses `SNAPSHOT_LOCAL_DIR` instead of S3, for offline work.

## 2. Build the index: `ingest index`

```sh
uv run ingest index --dry-run --dump dumps/   # chunk only, one JSONL per source
uv run ingest index                           # chunk, embed (Albert), index, swap the alias
uv run ingest index --only judilibre          # rebuild one source, copy the others
```

What gets ingested is set by the config file (`--config`, default `config/local.toml`):
- `include`: the sources to build.
- `snapshots`: `latest` or a pinned snapshot id per dataset.
- `embedding`: the canonical model id and its dimension.

Each run builds a new `{alias}-{timestamp}` index and copies in the chunks of the sources it does not rebuild. It then moves the alias and deletes the older `{alias}-*` indices. Use another `SEARCH_INDEX` for tests, without a hyphen after `chunks` (e.g. `chunks_test`): `chunks-*` would match it.

The index `_meta` records:
- the schema version, embedding model id and dimension, and chunker version
- the snapshots used by each source

A partial run (`--only`, or a shorter `include`) is refused when the current index was built differently: legacy ingestion, another schema major version, or another model.

## Data contract

`src/ingestion/contract.py` holds the pydantic models. The JSON schema and the index mapping (`mapping.py`, one vector field per engine) follow from them:
- `uv run ingest schema` regenerates the schema.
- CI checks that the committed schema is up to date (`--check`).
- `schema/examples/` has one example per source. The api tests read them through the api's own code.

Document ids are deterministic: `{source}:{idcc or "-"}:{metadata.id}:{metadata.idx}`. `doc_hash` covers the stored fields; `embed_hash` covers the model id and the embedded text.

Versioning:
- An additive change bumps the minor version of `SCHEMA_VERSION`.
- Any other change bumps the major version: a new schema file and a full rebuild.
- `CHUNKER_VERSION` changes whenever the chunk text changes for unchanged inputs.

## Checks

```sh
uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest
UPDATE_EXAMPLES=1 uv run pytest tests/test_sources.py   # regenerate schema/examples/
```
