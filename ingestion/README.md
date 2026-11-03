# Ingestion

Builds the search index that the api searches (alias `chunks`), on OpenSearch or Elasticsearch.

Inputs:
- raw source **snapshots** on S3: the code du travail (LEGI), collective agreements (KALI), Cour de cassation decisions (Judilibre), company agreements (ACCO)
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
uv run ingest fetch acco --from-dir path/to/results/accords   # company agreements, see below
```

Each run writes an immutable snapshot, then points `LATEST` to it:

```
{S3_PREFIX}{legi|kali|judilibre|acco}/{snapshot_id}/manifest.json   # files with sha256, upstream version
{S3_PREFIX}{legi|kali|judilibre|acco}/{snapshot_id}/<files>
{S3_PREFIX}{legi|kali|judilibre|acco}/LATEST.json
```

Snapshot ids:
- npm packages: the package version, e.g. `2.575.0`.
- Imported directories: the package version plus a content hash, e.g. `3.473.0-local.0429ef96`.
- Judilibre: the UTC date.
- ACCO: the UTC date of the import plus a content hash, e.g. `20261028-local.5d6dc65b`.

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

### Company agreements (ACCO)

`accords_entreprise` is a set of *accords d'entreprise* from the Légifrance ACCO fund, collected by keyword (for now, the heat agreements: "canicule", "fortes chaleurs"...) with `legifrance_acco.py`, which writes `results/accords/<id>.json` (the `/consult/acco` response) and the original `.docx`/`.odt` next to it, and `results/ids.json` (the search). There is no download in `ingest`: import the `accords/` directory.

```sh
uv run ingest fetch acco --from-dir path/to/results/accords
```

- The snapshot keeps one JSON per agreement, without its base64 copy of the original file (84 MB instead of 716 MB for 2,399 agreements).
- The API cuts the extracted text at 100,000 characters. From 99,000, the text is read again from the original file (standard library only, `text/office.py`), and `attachment.content_source` records where it came from (`api`, `docx`, `odt`, or `api-truncated` when the original could not be read). The manifest counts them in `upstream.text_sources`.
- The manifest also records the search criteria (`upstream.search`, from `ids.json`).
- Re-importing the same content is a no-op.

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

The company agreements are not in `config/local.toml` yet: they have their own config and their own index, so the shared `chunks` alias and the api are untouched.

```sh
SEARCH_INDEX=chunks_acco uv run ingest index --config config/acco.toml --dry-run --dump dumps/
SEARCH_INDEX=chunks_acco uv run ingest index --config config/acco.toml
```

Chunks of an agreement: split on its "Article N" headings (else its numbered headings, else one section), table of contents removed, long sections cut at 4,096 characters. The text starts with `{agreement title} > {part} > {article}`, not the company, so the embedding stays about the clause; the company, SIRET, sector, nature, signature date, themes and unions are metadata (schema 1.1.0). The ids are `{ACCOTEXT id}-{section}`, with `initial_id` the agreement. To merge them into the shared index, add `accords_entreprise` to `local.toml` and empty `OPTIONAL_SOURCES` in `contract.py` (the api must list the source first).

The index `_meta` records:
- the schema version, embedding model id and dimension, and chunker version
- the snapshots used by each source

A partial run (`--only`, or a shorter `include`) is refused when the current index was built differently: legacy ingestion, another schema major version, or another model.

## 3. Update the index in place: `ingest sync`

```sh
uv run ingest sync --dry-run          # what would change, per source: no write, no Albert call
uv run ingest sync                    # embed and write only what changed
uv run ingest sync --only judilibre
```

`index` rebuilds everything; `sync` diffs each source against the live alias and writes the difference. Per chunk (`_id` = `chunk_id`):

| in the index | action |
|---|---|
| same `doc_hash` | nothing |
| same `embed_hash`, other `doc_hash` | metadata update, the vector stays (e.g. a code du travail article renumbered: the CDTN pages that link to it) |
| other `embed_hash`, or not there yet | embed, then index |
| not there yet, but its text is already in the source (the `idx` shifted) | index with the existing vector |
| no longer produced | delete |

Guards, set in the `[sync]` table of the config (exit code 2, nothing written; `--allow-prune` skips them):
- a source that produces no chunk while the index has some;
- more than `max_delete_ratio` (10%, `per_source` overrides) of a source deleted, once over `min_deleted` chunks.

A source that is in the index but no longer in the include list is reported, and deleted only with `--prune-excluded`.

Everything is read, diffed and embedded before the first write, and the index `_meta` is updated last (snapshots of the synced sources, `synced_at`): after a failure the next `sync` repairs the index by diffing again. `sync` is refused (exit code 1, run `ingest index`) when there is no index, or its `_meta` has another schema major version, model, dimension or chunker version.

Limits:
- No lock: do not run two `sync`, or a `sync` during an `index`.
- A large change (a new model, a rewritten source) is cheaper to rebuild with `index`; `sync` holds the new vectors in memory until it writes.
- Updating a vector in the HNSW graph is a delete plus an insert: after big runs, `POST {index}/_forcemerge` off-peak.

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
