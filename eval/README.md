# Judge evaluation

Measures how well an LLM reproduces the human verdicts (`correct_en_droit`,
`suffisant`, `intelligible`) on `dataset/18q_human.json`: 184 answers to 18 questions.

## Setup

```sh
cd eval
uv sync                  # Python 3.12 + dependencies
cp .env.example .env     # ALBERT_API_KEY, MISTRAL_LLM_API_KEY, LITELLM_API_KEY
```

Models are declared in `config/models.toml` (Albert, Mistral and the Scaleway models,
all through an OpenAI-compatible `/v1` API; Scaleway is reached through the shared
LiteLLM gateway, hence the `scaleway/` prefix of its ids). Keys stay in `.env`; the file
only names the variables.

## Usage

```sh
# 1. No model needed: baselines only (majority, answer length, copy of correct_en_droit)
uv run judge-eval run --baselines --run-id baselines
uv run judge-eval report --run-id baselines

# 2. Look at exactly what a model receives
uv run judge-eval prompt --criterion suffisant --item id_1

# 3. Real models: set the keys, check that each model id is served
uv run judge-eval models --all
uv run judge-eval check      # one real call per model: key, params, JSON mode, parsing
uv run judge-eval run --models config/models.toml --baselines --limit 5 --run-id smoke
uv run judge-eval run --models config/models.toml --baselines --run-id full
uv run judge-eval report --run-id full
```

- Runs are stored in `runs/<run-id>/` (git-ignored) and are **resumable**: re-running the
  same command only retries API errors; unparsable replies are kept as results.
- A run refuses to continue if the dataset, the prompt files or a model's settings changed
  since it started: use a new `--run-id`.
- `check` stores nothing and makes one call per model (a few tokens each). It reports
  per model the result, the response mode actually used, `finish_reason`, latency and
  the served id, and exits 1 if any model does not answer in a usable form. Run it
  after changing `models.toml`, before a smoke or full run.
- `--only albert,mistral` restricts to some models of the file, `--criteria` to some criteria.
- `run` first checks every model id against its endpoint and stops on an unknown one
  (`--skip-check` to bypass). On rate limits (429) lower `concurrency` in the models file;
  failed calls are retried when you re-run.
- Pin dated model ids rather than `*-latest` aliases; each prediction records the id the
  server actually answered with (`served_model`).
- Outputs of `report`: `report.md`, `metrics.csv` (with confusion counts), `pairwise.csv`,
  `per_question.csv`, `disagreements.csv` (judge vs human, with the judge's reasoning).

## Reading the results

- Compare with the `baseline:*` rows first: majority class already gets 62 / 53 / 67 %.
- `suffisant` is almost implied by `correct_en_droit` in the human labels (84 % identical),
  so look at the `suffisant | correct=Oui` table too.
- Confidence intervals resample the 18 questions; they are wide. Do not rank models on
  small gaps; use the paired comparison table.
- The criterion definitions in `prompts/v1/` are drafts inferred from the column names.
  Replace them with the annotation guidelines before drawing conclusions.

## Retrieval evaluation

Every step, and how the labelling model is chosen (`sample-pairs`, `probe-labellers`,
`compare`) and the local labelling page (`ui-export`), is described in [retrieval/README.md](retrieval/README.md); this is the short
version.

Measures the search part of the RAG (ES kNN / hybrid, then the Albert rerank), not the
answers. Scope for now: the fiches pipeline of `web/src/modules/api/prepare.ts`
(`page_fiche_ministere_travail`, `fiches_service_public`, `information`, plus
`contributions` unless the IDCC pipeline selects chunks). Code du travail, IDCC and
jurisprudence are not scored yet.

What is labelled is a **document** (`metadata.id`), not a chunk: the ES chunk `_id`
changes at every ingestion. Each label stores the sha256 of the text it was given and
is ignored by `report` once the document text changes.

Data, all under `retrieval/`:

- `queries.jsonl`: 340 queries (`judge18`, `prod` sampled and anonymised from a Metabase
  export, `idcc22`), each with a fixed dev/test `split` (tune the labeller on dev only).
- `prompts/v1/`: `system`, `guideline` (0 = useless, 1 = useful but partial, 2 = answers
  directly) and `user` prompts. **The guideline is a draft**: edit it before labelling,
  and bump the version (`prompts/v2/`) after any change.
- `qrels/`: one labels file per labeller (`llm:<model>`, `human:<name>`), committed.
- `.local/` (git-ignored): anonymisation audit, audit sheet and its key.
- `runs/<run-id>/` (git-ignored): `rankings.jsonl` (what each variant returned),
  `docs.jsonl` (document text snapshot), then `report.md` and CSVs.

```sh
# Queries (done once; `add-queries` appends without touching existing splits)
uv sync --extra anonymise
uv run retrieval-eval add-queries --file dataset/dataset_idcc.json --source idcc22

# 1. Run the variants (knn, hybrid, hybrid+rerank) against the API; needs AUTH_API_KEY
#    and API_BASE_URL in .env. Start with the dev split.
uv run retrieval-eval pool --run-id retrieval-1 --split dev

# 2. Look at what the labeller would receive, and size the run before paying for it
uv run retrieval-eval prompt --run-id retrieval-1 --query-id <id> --doc-id <id>
uv run retrieval-eval label  --run-id retrieval-1 --model albert/gpt-oss-120b --dry-run

# 3. LLM labels (calls the model; refuses more than --max-pairs 500 calls)
uv run retrieval-eval label  --run-id retrieval-1 --model albert/gpt-oss-120b

# 4. Blind human audit: label the sheet with the guideline, then import it
uv run retrieval-eval audit-export --run-id retrieval-1 \
    --llm-qrels retrieval/qrels/llm-albert-gpt-oss-120b-v1-<hash>.jsonl --split dev
uv run retrieval-eval audit-import --sheet retrieval/.local/audit_sheet.csv --annotator remi
uv run retrieval-eval agreement --reference retrieval/qrels/human-remi.jsonl \
    --other retrieval/qrels/llm-albert-gpt-oss-120b-v1-<hash>.jsonl

# 5. Retrieval metrics
uv run retrieval-eval report --run-id retrieval-1 \
    --qrels retrieval/qrels/llm-albert-gpt-oss-120b-v1-<hash>.jsonl

# Check the port against production (web /api/generate; needs WEB_BASE_URL, DEBUG_API_KEY)
uv run retrieval-eval web-snapshot --run-id retrieval-1 --source idcc22
uv run retrieval-eval web-check --run-id retrieval-1
```

Reading the report:

- Trust the numbers only as far as `agreement` allows: it gives the weighted kappa of the
  LLM against the human sample, with intervals that resample queries.
- Intervals resample whole queries, and variants share the draws, so the paired table is
  the one to compare variants with.
- A document without a label counts as not relevant. `judged@10` is the share of the
  top 10 that has a label: when it is low, scores are lower bounds. Recall is relative to
  the pool (documents some variant returned), so it cannot see what no variant found.
- `hybrid+rerank` is production: its first 10 documents are what the LLM reads. The
  Python port of the web pipeline (`pipeline.py`) must follow `prepare.ts`;
  `tests/test_pipeline.py` checks its constants against `web/src/constants.ts`.
- `/anonymize` is not called by `pool`: the queries are already anonymised.

## Answer evaluation

`answer-eval` compares answer models on the prompt the web builds for `/api/generate`,
with the fiches a labeller graded useful instead of the live search. See
[generation/README.md](generation/README.md).

```sh
uv run answer-eval contexts --run-id answers-idcc22   # freeze sources (calls the API)
uv run answer-eval generate --run-id answers-idcc22   # models of config/generators.toml
uv run answer-eval judge --run-id answers-idcc22 --only scaleway/scaleway/llama-3.3-70b-instruct
uv run answer-eval report --run-id answers-idcc22
```

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format .
```
