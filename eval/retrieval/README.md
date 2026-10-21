# Retrieval evaluation: the pipeline, step by step

Measures the **search** part of the RAG (Elasticsearch kNN and hybrid retrieval, then the
Albert rerank), not the answers. Scope for now: the *fiches* pipeline of
`web/src/modules/api/prepare.ts` (`page_fiche_ministere_travail`,
`fiches_service_public`, `information`, plus `contributions` unless the IDCC pipeline
selects chunks). Code du travail, IDCC chunks and jurisprudence are not scored yet.

The code is the `retrieval_eval` package (`src/retrieval_eval/`), run with
`uv run retrieval-eval <command>` from `eval/`. The commands and their short usage are in
`eval/README.md`; this file explains what each step does.

```
queries.jsonl ──► pool ──► label ──► audit-export ──► (human) ──► audit-import
                    │         │                                        │
                    │         └──────────────► agreement ◄─────────────┘
                    └──────────────────────────► report ◄── qrels
```

Only `pool` (the SRDT API) and `label` (a chat model) use the network. Every step before
`report` writes a file, so it can be resumed or inspected.

## What is ranked and labelled

- The unit is a **document** (`metadata.id`, the cdtn id), not a chunk. The ES chunk
  `_id` changes at every ingestion; the document id does not.
- A label stores the sha256 of the document text it was given. If the text changes, the
  label is ignored by `report` and the pair is labelled again by `label`.
- Grades: **2** answers directly (or is the legal basis), **1** useful but partial,
  **0** useless. The definition is `prompts/v1/guideline.fr.md`. It is a draft: edit it
  before labelling, and bump the version (`prompts/v2/`) after any change.

## Files

| Path | Content | Committed |
|---|---|---|
| `retrieval/queries.jsonl` | one query per line: `query_id`, `text`, `source` (`judge18`, `prod`, `idcc22`), `idcc`, `length_bucket`, `theme`, fixed `split` | no (real user questions, until reviewed) |
| `retrieval/prompts/<version>/` | `system`, `guideline`, `user` prompts (French) | yes |
| `retrieval/qrels/*.jsonl` | one file per labeller (`llm:<model>`, `human:<name>`) | no (real user questions, until reviewed) |
| `retrieval/.local/` | anonymisation audit, audit sheet and its key | no |
| `runs/<run-id>/rankings.jsonl` | per (query, variant): the ranked document ids and scores | no |
| `runs/<run-id>/docs.jsonl` | text snapshot of the documents that were pooled | no |
| `runs/<run-id>/config.json` | hash of the queries file, `top_k`, variants | no |
| `runs/<run-id>/report.md`, `*.csv` | the report | no |
| `runs/<run-id>/web_snapshots/<timestamp>/` | `web-snapshot`: the web's `/api/generate` responses, the port's rankings, `meta.json`; `web-check` adds `compare.jsonl` and `report.md` | no |

## Step 0: queries (once, local)

`sample-queries` built the set: the 18 judge-eval questions plus 300 real questions
sampled from a Metabase export (capped per user, stratified by length bucket), anonymised
with spaCy (`fr_core_news_md`), with a theme and a length bucket, and a **dev/test split
fixed once**. `add-queries` appends more questions (the 22 of `dataset/dataset_idcc.json`)
without touching existing splits: re-running `sample-queries --force` would redraw them.
Both write a local CSV (`.local/selection_audit.csv`) with original and anonymised text,
so the anonymisation can be reviewed by hand.

The set has 340 queries: 64 dev and 276 test, 61 with an IDCC.

## Step 1: `pool` (calls the API, no LLM)

```sh
uv run retrieval-eval pool --run-id retrieval-1 --split dev
```

Needs `API_BASE_URL` and `AUTH_API_KEY` in `eval/.env` (`API_BASE_URL` may include or omit
`/api/v1`). For each query:

1. **Contributions flag.** With an IDCC, it calls `/idcc/search` then `/rerank`, as the web
   does. The generic `contributions` collection is added to the content search only if
   that selected nothing. Without an IDCC it is always added.
2. **Two searches** over the fiches collections, 200 chunks each: kNN only
   (`hybrid=false`) and hybrid (kNN + BM25, fused by RRF).
3. **Merge by document**: the best chunk of each document is kept, the text of its other
   chunks is appended (`mergeChunksByDocumentId` in the web code).
4. **Three rankings** are stored:
   - `knn`: the merged kNN order;
   - `hybrid`: the merged hybrid order, before the reranker;
   - `hybrid+rerank`: **production**. The first 64 and the next 64 merged documents go to
     `/rerank`, and all results are sorted by rerank score. The LLM reads its first 10.
5. **Document text.** For every document in the top `--depth` (default 20) of any variant,
   the full text is fetched through `/docs/retrieve` (batches of 10, each document once
   across queries).

Options: `--limit N` (a spread sample of N queries), `--variants`, `--top-k` (200),
`--depth` (20), `--concurrency` (4), `--max-retries` (3). Server errors and timeouts are
retried; other HTTP errors fail the query. A failed query is listed and the exit code is
1; re-running the same command retries only those. The run refuses a changed queries file
or `--top-k` (use a new `--run-id`); variants can be added to an existing run.

The Python port of the web pipeline is `src/retrieval_eval/pipeline.py`. It must follow
`prepare.ts`: `tests/test_pipeline.py` checks its constants against
`web/src/constants.ts`. `/anonymize` is not called, because the queries are anonymised.

### Checking against production: `web-snapshot` (calls) and `web-check` (local)

The constants test does not show that the port selects the same documents as the web.
`web-snapshot` calls the web's `POST /api/generate`, the path a user's question takes
(anonymize, IDCC, fiches, code du travail, jurisprudence, then the LLM answer), and saves
each response whole. Right after each call it runs the port on the text the web searched
(the web's `anonymized_question`), so both see the same index and reranker.
`web-check` then compares the files and makes no call:

- **parity**, web vs port: the ordered top 10 fiches, and whether the generic
  `contributions` collection was added (the web adds it when it kept no IDCC chunk);
- **drift**, web vs the stored `hybrid+rerank` ranking of the run, or with `--against`,
  vs an earlier snapshot (then IDCC, code du travail and jurisprudence lists too);
- whether `/anonymize` changed the stored query text: the stored run then searched
  another text than production. Those queries are listed apart (`text` in the drift
  column) and left out of the drift count, which then reflects index, reranker or
  web changes only. Parity is not affected: the port searches the web's text.

```sh
# needs WEB_BASE_URL and DEBUG_API_KEY (the web's) besides AUTH_API_KEY; each query
# runs an LLM generation plus the jurisprudence filter (one LLM call per decision)
uv run retrieval-eval web-snapshot --run-id retrieval-1 --source idcc22
uv run retrieval-eval web-check --run-id retrieval-1            # latest snapshot
uv run retrieval-eval web-check --run-id retrieval-1 --against <earlier timestamp>
```

`web-snapshot --port-only` skips the web (no LLM call, no `WEB_BASE_URL` /
`DEBUG_API_KEY`): it asks the API's `/anonymize` for the text, as the web does, then
runs the port on it, like `pool`. Cheap enough for every query (`--split all`, no
`--source`). It has no parity, only drift: against the stored run, or with `--against`
against the port rankings of another snapshot (a web snapshot has them too).

`web-snapshot` writes a new `web_snapshots/<timestamp>/` folder each time; `--resume
<timestamp>` completes one instead (failed web calls and missing port rankings only).
`web-check` exits 1 on a parity difference, or with `--against` on any drift. With
`--against` it writes `report-vs-<snapshot>.md` (and `compare-vs-<snapshot>.jsonl`),
so the comparison with the stored run is kept. Results and the measured noise are
logged in [web-checks.md](web-checks.md).

Reading a difference: rerun `web-snapshot` once. A parity difference that moves between
snapshots is reranker noise; one that stays is a port bug. Known causes: the web's
`mergeChunksByDocumentId` puts all-digit document ids first, which changes the order of
documents with tied scores; a failing `/idcc/search` makes the web add `contributions`
(the port fails instead); `/docs/retrieve` can return fewer than 10 documents.
Jurisprudence is listed but not scored: an LLM filters it, and the route does not
return the candidates before the filter.

## Step 2: pools and prompt check (local)

The **pool** of a query is the union of each variant's top N documents, N being `--depth`
of `label`. It is recomputed from `rankings.jsonl` every time, so N can change without
re-running `pool`. Pooling several variants keeps the gold labels from depending on one
retriever: on the first queries, the kNN top 10 shares only 2 to 6 documents with
production's top 10.

```sh
uv run retrieval-eval prompt --run-id retrieval-1 --query-id <id> --doc-id <id>
```

prints the exact messages the labeller would receive.

## Step 3: `label` (calls a chat model)

```sh
uv run retrieval-eval label --run-id retrieval-1 --model albert/gpt-oss-120b --split dev --dry-run
uv run retrieval-eval label --run-id retrieval-1 --model albert/gpt-oss-120b --split dev
```

1. Builds the (query, document) pairs of the pool (`--depth`, default 10).
2. **Always prints the pair count and a token estimate.** `--dry-run` stops there. A run
   above `--max-pairs` (default 500) is refused.
3. Each pair is sent as a system prompt (instructions + guideline) and a user prompt
   (question, IDCC if any, document). The document is cut at `--max-chars` (default
   12,000) with a marker, and the label is flagged `truncated`.
4. The model answers `{"reasoning", "grade"}` (0, 1 or 2) at the temperature set in
   `config/models.toml`. The JSON mode steps down from `json_schema` to `json_object`
   to plain prompting if the endpoint rejects it. A grade is never guessed from free text.
5. Each label is appended to `retrieval/qrels/llm-<model>-<version>-<hash>.jsonl` with
   the document text hash, the prompt version, the **prompt hash** (the prompt files and
   `--max-chars`), the latency and the token counts. Unusable replies go to
   `<file>.failures.jsonl`.

Resume rules: a pair is skipped if the same labeller already labelled the same document
text with the same prompt hash, so changing `--max-chars` or editing a prompt file
relabels (into another file, named after the new hash). A parse error is final (the
answer would be the same); an API error is retried on the next run.

`label --pairs <key.json>` labels exactly the pairs of a key file written by
`sample-pairs`, instead of the pool; `--model` can be repeated and the models run one
after the other. `--max-pairs` then counts pairs x models.

**Truncation.** On the first 2 queries, 32 of 72 documents exceeded 12,000 characters
(median 10,300, maximum 56,600). Decide `--max-chars` before a real run: raising it costs
more tokens, keeping it means a grade can rest on part of a document.

## Step 4: `audit-export` (local)

```sh
uv run retrieval-eval audit-export --run-id retrieval-1 --llm-qrels <qrels> --split dev
```

Samples up to `--n` (150) LLM-labelled pairs, at most `--per-query-cap` (3) per query,
split evenly over six cells: LLM grade (0/1/2) × in production's top 10 or not. The quotas
are set before the per-query cap is applied, so that the rare cell (documents production
did not rank) is not starved.

It writes `.local/audit_sheet.csv` (query, IDCC, title, source, URL, document, empty
`grade` and `comment`) and `.local/audit_key.json` (which holds the LLM grades). Give the
annotator **only the sheet and the guideline**: the sheet contains no LLM grade or
rationale.

## Step 5: `audit-import` (local)

```sh
uv run retrieval-eval audit-import --sheet retrieval/.local/audit_sheet.csv --annotator remi
```

Reads the filled sheet and writes `retrieval/qrels/human-<annotator>.jsonl`. Blank rows are
skipped and counted. A grade other than 0, 1 or 2, or an unknown row id, stops the import.

## Step 6: `agreement` (local)

```sh
uv run retrieval-eval agreement --reference retrieval/qrels/human-remi.jsonl --other <llm qrels>
```

Compares the two label sets on the pairs both labelled (same query, document and text
hash). Reports exact agreement, quadratic-weighted kappa, and kappa for "useful or not"
(grade ≥ 1) and "answers directly or not" (grade ≥ 2), with 95% intervals from resampling
whole queries, and the 3×3 confusion matrix. This is what tells you how far the LLM labels
can be trusted.

## Step 7: `report` (local)

```sh
uv run retrieval-eval report --run-id retrieval-1 --qrels <llm qrels>
```

1. Picks one labeller (`--labeller` if the files hold several) and drops labels whose
   document text changed since the snapshot.
2. For each query that has at least one label and each variant, computes at k = 5, 10, 20
   (`--ks`): recall and precision at "grade ≥ 1" and "grade ≥ 2", nDCG (gain 2^grade − 1,
   ideal ranking = the query's labelled documents), MRR, and `judged@k`.
3. A query with no relevant document at a threshold is **left out** of that metric's
   mean (the report shows how many queries each mean covers), never counted as 0. A
   document with no label counts as not relevant.
4. Bootstraps over whole queries (`--bootstrap`, default 1000), with the same draws for
   every variant so differences are paired. Done for all queries and for slices: dev,
   test, with / without IDCC, and the three length buckets.
5. Writes `report.md`, `metrics.csv`, `pairwise.csv` and `per_query.csv` in the run.

## Choosing the labeller

Which model labels is decided by agreement with a human on the same pairs, not by
reputation: the judge-eval ranking does not transfer (other task, best kappa 0.34 with
overlapping intervals). The candidates are in `config/labellers.toml` (8 models, dated
ids, one entry per set of weights); `judge-eval run` does not use that file.

**Rule, fixed before any human labelling.**

- Document length: `--max-chars 120000` for every model. 44% of documents exceed the
  default 12,000 characters, and pooled documents reach 119,000 (7 of 818 exceed 60,000;
  8 of the 120 sampled pairs do), about 35k tokens, which every candidate's context
  holds. The sheet shows the same text: up to 120,000 characters over `document` and its
  continuation columns `document_2` to `document_4` (a spreadsheet cell holds about
  32,000), each pointing to the next. (First set at 60,000 from 72 documents, raised
  once the whole pool was measured.)
- Sample: 120 pairs from the 64 dev queries, **stratified by what three fast screener
  models graded** over the whole dev pool (1,181 pairs): about 1 pair in 6 is relevant
  and a random sample is mostly obvious zeros, which tell the models apart on nothing.
  Strata: every screener >= 1 with a 2 (30 pairs), every screener >= 1 without a 2 (20),
  screeners disagree (40), every screener 0 (30, to measure what they miss). The human
  still labels blind: the screeners choose *which* pairs are shown, never what the
  human sees. Each pair stands for `pool / sampled` pairs of its stratum and carries
  that weight, so kappa and its intervals estimate the **pool**. Screeners:
  `albert/gemma-4-31b-it`, `albert/mistral-small-3-2-24b-instruct-2506`,
  `scaleway/llama-3.3-70b-instruct`. The first design (a sample drawn by provenance
  alone, kept as `sample-pairs` without `--screeners`) was dropped for that reason.
- The bar applies to the **pool-weighted** kappas (the unweighted kappas of the
  enriched sample are shown beside them; if the two give different verdicts, the report
  says so rather than choosing). This is a change from the first wording of the rule,
  made when the sample design changed, before any human label existed for it.
- A model is **eligible** if its weighted kappa against the human reaches **0.6 on
  "useful or not"** (grade >= 1) **and 0.5 on "answers directly or not"** (grade >= 2).
  Point estimates decide; `compare` also says when the lower interval bounds reach it.
- A model is **shortlisted** if it is eligible and its paired kappa difference against
  the best model (3-grade weighted kappa) has an interval containing 0. Among the
  shortlisted, the fastest or cheapest is chosen; price is not known to the tool.
- If no model is eligible, do not choose the least bad one: fix the guideline, or use
  the majority of three models, then compare again.
- Selection is on dev; the chosen model is then audited on the **test** split
  (`audit-export`), whose pairs played no part in the choice.

**Frozen on 2026-10-19:** guideline `prompts/v1/guideline.fr.md` (sha256 starting
`e534d4a2e000`), approved by the annotator. With the prompt files and
`--max-chars 120000`, the prompt hash is `a3918e4a`; it is in the name of every qrels
file the comparison writes. A different hash means a different experiment: do not mix
labels across it.

**Steps** (all local except 2 and 5):

1. Edit and freeze `prompts/v1/guideline.fr.md`: the human and every model must work
   from the same final guideline (a later edit means a new version and a new sample).
2. `uv run retrieval-eval probe-labellers`: one real call per candidate on a built-in
   pair. Catches an unserved id, a missing key, a model rejecting `temperature`, no JSON
   mode, a reply that does not parse. Fix with `params = {}` or by dropping the model.
3. Screen the whole dev pool with the three screeners (the same prompt hash as the
   comparison, so these labels are reused in step 5 and cost nothing twice):
   `label --run-id <run> --split dev --depth 10 --max-chars 120000 --max-pairs 4000
   --model albert/gemma-4-31b-it --model albert/mistral-small-3-2-24b-instruct-2506
   --model scaleway/llama-3.3-70b-instruct`. Then
   `sample-pairs --run-id <run> --split dev --depth 10 --n 120 --screeners
   retrieval/qrels/llm-*-v1-<hash>.jsonl` (the three files) prints the strata with their
   pool size, sample size and weight, and writes `.local/selection_sheet.csv` (what the
   human sees) and `.local/selection_key.json` (strata and weights, never shown). It
   refuses to overwrite an existing sheet without `--force`: it may hold hours of labels.
   Without `--screeners` it draws by retrieval provenance only, with no model. Pass
   `--sheet`/`--key` (and `ui-export --key ... --out ...`) to keep several samples side
   by side: the screened one of this run is `.local/screened_{sheet.csv,key.json}` and
   `.local/screened_labelling.html`.
4. Label the pairs, blind, either in the CSV sheet or in the local page:
   `uv run retrieval-eval ui-export --run-id <run>` writes `.local/labelling.html`, one
   self-contained file (about 3 MB, questions and documents embedded, no network).
   Open it in a browser: the guideline is one key away (`g`), grade with `0` `1` `2`
   (it moves to the next pair; the same key again clears the grade), `f` flags a pair to
   come back to, `c` types a comment, arrows navigate, `n` jumps to the next unlabelled
   one, and the list on the left filters by status. Labels autosave in the browser and
   the page estimates the time left. **Click `Export CSV` regularly**: browser storage
   can be cleared, and Safari or a private window may not keep it (the page warns).
   `Load CSV` restores an earlier export. Then
   `audit-import --sheet <exported csv> --key retrieval/.local/selection_key.json --annotator <name>`;
   the page's CSV and the `selection_sheet.csv` both work there.
5. For each model, on exactly those pairs:
   `label --run-id <run> --pairs retrieval/.local/selection_key.json --max-chars 120000
   --model <name> [--model <other> ...] --max-pairs 1000` (use `--dry-run` first: 120
   pairs x 8 models is 960 calls, about 4M prompt tokens plus any reasoning output).
6. `uv run retrieval-eval compare --key retrieval/.local/selection_key.json --run-id <run> --human retrieval/qrels/human-<name>.jsonl
   --models-qrels retrieval/qrels/llm-*.jsonl`. It writes `compare.md` and `compare.csv`:
   per model the coverage, parse and API errors, kappa on the three views with
   intervals, the paired difference against the best, over- and under-grading, latency,
   tokens, and whether it is eligible and shortlisted. Kappas are on the pairs every
   model labelled, with the same bootstrap draws over queries for all models.
7. Ceiling, a week later: `sample-pairs --run-id <run> --subset-of
   retrieval/.local/selection_key.json --n 30` makes a blind sheet of 30 of the same pairs
   under new ids; `audit-import ... --annotator <name>-pass2`; then `agreement` between
   the two passes. If that kappa is below the bar, the bar cannot be met and the
   guideline, not the model, is the problem.

Limits: 120 pairs over 40 or more queries separates clearly better models from clearly
worse ones, not close ones, which is why the rule shortlists on the paired interval and
then picks on cost. One annotator means model error and the annotator's own
inconsistency cannot be told apart without step 7.

## Building the dataset and reporting

Once a labeller is chosen (see above), it grades **every pooled pair**, not only a sample,
and the graded pairs become the dataset and the basis of the retrieval metrics. Labels
stay graded 0/1/2 everywhere; binary readings (grade >= 1 "useful", grade 2 "answers
directly") are thresholds used when computing a metric, never stored as labels.

```sh
# 1. Grade the whole pool (resumes: pairs already graded with the same prompt are skipped).
#    Run again until `api_errors` is 0: a dropped connection is retried, not lost.
uv run retrieval-eval label --run-id retrieval-1 --split all --depth 20 \
    --max-chars 120000 --max-pairs 12500 --model scaleway/llama-3.3-70b-instruct

# 2. Metrics of the retrieval variants, and the labeller's error profile against the
#    human sample (graded view first, then the two binary views)
uv run retrieval-eval report --run-id retrieval-1 \
    --qrels retrieval/qrels/llm-scaleway-llama-3.3-70b-instruct-v1-<hash>.jsonl \
    --human retrieval/qrels/human-remi-revised.jsonl --key retrieval/.local/screened_key.json \
    --ks 5 10 20

# 3. The dataset: pairs, queries, documents and a data card (local, not for committing)
uv run retrieval-eval export-dataset --run-id retrieval-1 \
    --qrels retrieval/qrels/llm-scaleway-llama-3.3-70b-instruct-v1-<hash>.jsonl \
    --human retrieval/qrels/human-remi-revised.jsonl --key retrieval/.local/screened_key.json
```

- `report` gives, per retrieval variant and slice, recall, precision, MRR and nDCG at 5, 10
  and 20 with intervals over queries. nDCG uses the 0/1/2 gains; the others are shown at
  both thresholds. `hybrid+rerank` is what production runs: its first 10 documents are
  what the answer step reads. With `--human` and `--key` it appends the **labeller error
  profile**: the 3x3 confusion, exact agreement, quadratic-weighted kappa, who grades
  higher, then precision, recall, F1 and kappa of the two binary views, all weighted to
  estimate the pool.
- The metrics trust the labeller's grades. Read them next to its error profile: a
  labeller that misses relevant documents lowers recall, one that over-grades lowers
  precision. Comparing variants is safer than reading an absolute level.
- `export-dataset` refuses to write if a pooled pair has no grade made on the stored
  document text (it names how many are missing), or if the grades were made with other
  prompts or another `--max-chars` than the ones passed. Its folder `retrieval/dataset/`
  holds `pairs.jsonl` and `pairs.csv` (grade, rationale, rank in each variant,
  `in_production_top10`, `human_grade` on the gold pairs), `queries.jsonl`,
  `documents.jsonl` and a generated `README.md` data card that states the labeller, the
  prompt hash, the grade counts, its error profile and whether it reaches the selection
  bar. It contains anonymised real user questions: keep it local until reviewed.

### One question at a time

```sh
Q=retrieval/qrels/llm-scaleway-llama-3.3-70b-instruct-v1-<hash>.jsonl
uv run retrieval-eval query-report --run-id retrieval-1 --qrels $Q --worst 20        # where production does worst
uv run retrieval-eval query-report --run-id retrieval-1 --qrels $Q --query-id q_15a3113a
uv run retrieval-eval query-report --run-id retrieval-1 --qrels $Q --search "traceur"  # words of the question
```

The report of a question shows the metrics of each variant on it alone, the 10 documents
production sends to the answer step with the labeller's grade, the rank each had in the
other variants and the labeller's reasoning, then the useful documents (grade 1 or 2)
production did not send, with their ranks. `--human <qrels>` adds your grade where you
gave one, `--out file.md` saves it. A question with a single "useful" document that is
generic usually points to a **gap in the corpus**, not a ranking problem.

## Reading the results

- Compare variants with the paired table, not by ranking small gaps.
- `judged@k` is the share of the top k that has a label. When it is low, scores are lower
  bounds. With labelling depth 10, `judged@10` is close to 1 by construction for the
  variants that were pooled; it matters at k = 20, and for variants added later.
- Recall is relative to the pool. A relevant document that no variant returned cannot be
  seen.
- Small slices (IDCC, a length bucket, dev) have wide intervals; the report prints query
  counts next to them.

## Known rough edges

- `--split` defaults differ: `pool` and `label` use `dev`, `audit-export` uses `test`.
  Label the split you export, or pass `--split` explicitly. `sample-pairs` requires it.
- `/docs/retrieve` still answers in Elasticsearch order, but the web now sorts the
  retrieved documents back into rerank order (`getFullContentFromReranked`), so the order
  the LLM reads matches the rankings measured here (rerank score order).
- The IDCC pipeline itself (conventions, `contributions_idcc`) is not scored; IDCC only
  decides whether `contributions` is searched.
