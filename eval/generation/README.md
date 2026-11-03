# Answer evaluation

This compares answer models on the 22 IDCC questions. Every model gets the same
prompt. That prompt is what the web builds for `/api/generate` (first question),
with retrieval held fixed.

## What the prompt contains

| Block | Source |
|---|---|
| Instructions | `generate_instruction` / `generate_instruction_idcc` exported from `web/src/prompts` to `prompts/web-v2.0.json` |
| Fiches officielles | Documents the llama labeller graded ≥ 1 for the question. Grade 2 comes first, then production rank; at most 10. The text is the snapshot the labeller read. |
| Code du travail | Live, as `searchArticles`: articles cited by those fiches (`linked_from`), reranked, top 5 |
| Conventions collectives | Live, as `searchIDCC`: reranked, top 5. Only for questions with an IDCC |
| Jurisprudence | Live, as `searchJurisprudence`: judilibre search, reranked, top 5, then the web's LLM filter (one OUI/NON call per decision with mistral-large-latest, `--filter-model`). A call failing twice keeps the decision; an unreadable reply drops it. Every candidate and verdict is stored in `jurisprudence_candidates`. |

The user message is the anonymised question, sent as is.

`contexts --from-run <run>` copies every block but the jurisprudence from another
run's contexts, unchanged and checked, and only runs the jurisprudence. Use it to
compare runs that differ by the jurisprudence only. The source is recorded in
`contexts.meta.json`.

`contexts` calls the API once and freezes the result in `runs/<id>/contexts.jsonl`. All
models of a run read the same prompt, and `config.json` refuses to mix runs made from
different contexts or templates.

## Keeping in step with the web

- `scripts/web_prompts.mjs export <file>` reads the templates from the TypeScript
  sources. It uses `web/node_modules/typescript`, so `npm ci` must have been run in
  `web/`.
- The commands warn when a web source changed since the export. When that happens,
  export to a **new** file (`web-v2.1.json`) and pass `--prompts`. Don't overwrite the
  file used by existing runs.
- `tests/test_answer_prompt.py` renders cases with the real TypeScript code and expects
  byte-identical output from `answer_eval/prompt.py`.

## Differences from production

- `clean_urls` (API post-processing, which needs Elasticsearch) is not applied. The
  answers are the raw model output.
- Production answers with `mistral-large-latest`, temperature 0.3, and no
  `max_tokens`. That is the `prod/` entry of `config/generators.toml`.
- Prompts reach about 340k characters (about 90k tokens). Models need a context of at
  least 128k tokens.

## Files of a run (`runs/<id>/`)

- **`contexts.jsonl`**: the frozen sources of each question.
- **`contexts.meta.json`**: the filter model, the templates hash, and the source run when
  `--from-run` was used.
- **`prompts.jsonl`**: the rendered messages (`answer-eval prompts`). Use
  `--query-id` to print one.
- **`answers.jsonl`**: one line per (generator, question).
  - Resumable; only `api_error` lines are retried.
  - `empty` means the model returned no text.
- **`judge/`**: a judge_eval run.
  - Items are named `<generator>::<query_id>`.
  - The judges see the question and the answer only, not the sources.
- **`report.md`**: the summary.
  - Answers, refusals, latency and tokens, plus the share of « Oui » per judge and
    criterion.
  - Refusals are found by matching the instructions' fixed sentences.
- **`answers.md`**: every answer side by side with its sources and verdicts.
- **`per_answer.csv`**: one row per answer and judge.

## Human labelling (blind)

Current campaign (run `answers-idcc22-j`, one labeller): [labelling-idcc22-j.md](labelling-idcc22-j.md).

Two ways to give the page to the labeller: hosted (below, the labels are saved in
a private repo and read back from there, no file to exchange), or one
self-contained HTML file:

```sh
uv run answer-eval label-export --run-id answers-idcc22-j    # labelling/answers-labelling.html
# send the HTML page only; the labeller exports a CSV from it
uv run answer-eval label-import --run-id answers-idcc22-j --file evaluations-….csv --annotator <name>
uv run answer-eval report --run-id answers-idcc22-j          # adds the "Human <name>" tables
```

- **The page.** It is one self-contained HTML file with no network access, in French.
  - There is one screen per question, and its answers are shown as A–D in an order shuffled per question (`--seed`).
  - Each answer gets Oui/Non on the judge's three criteria (definitions from `prompts/v1/<criterion>.fr.md`), plus a comment and a "to review" flag.
  - Each question also gets one label of its own, "Sources suffisantes pour répondre ?" (Oui/Non and an optional comment), above the folded block of the sources the models were given. It judges the retrieval, not the answers: were the fiches, Code du travail, CC and jurisprudence extracts enough to answer correctly? A question is complete when its answers and this label are.
  - Labels are saved in the browser as the labeller goes. In the self-contained file, "Exporter le CSV" downloads them and "Charger un CSV" reloads them; the hosted page has no CSV buttons, it saves to the repo.
- **Only the configured models.** `label-export` and `label-publish` keep only the answers of the models in `--models` (default `config/generators.toml`) and print the ones left out: a model removed from the file (gpt-oss) stays in `answers.jsonl` and in the judge runs, but never reaches the labeller.
- **Blinding.** Model names appear nowhere on the page. `labelling/key.json` maps each `label_id` (`07-C`, and `07-Q` for the question) to its answer: **do not send it**.
  - Answers are rendered from Markdown with raw HTML disabled.
  - `label-export` and `label-publish` refuse to overwrite an existing key without `--force`.
- **CSV (self-contained file).** Columns `label_id, correct_en_droit, suffisant, intelligible, sources_suffisantes, comment, flag, seconds`. One row per answer (`sources_suffisantes` empty), then one per question (`07-Q`: only `sources_suffisantes` and `comment`). CSVs from the older page, without the column, still import.
- **Import.** The import stops on an unknown `label_id`, on a value other than Oui/Non, or on an answer that changed after the page was built. A partly labelled answer is left out.
- **Output.**
  - `labelling/human-<name>.jsonl` (answers) and `labelling/question-labels-<name>.jsonl` (sources).
  - `labelling/dataset-<name>.json` in the `dataset/18q_human.json` format: `judge-eval run --dataset …/dataset-<name>.json` measures the LLM judges against this labeller.
  - `report` adds the share of questions with sufficient sources per labeller, and for each generator its refusals (CC refusals, on the questions with an IDCC, and "no information" refusals) on the questions with and without sufficient sources: a refusal despite sufficient sources is the model's failure, not the retrieval's.
- **Draft criteria.** The criterion definitions in `prompts/v1/*.fr.md` are marked as drafts (inferred from the column names of the 18q dataset). Replace them with the real annotation guideline before labelling if there is one, then rebuild the page.

### Hosted page (GitHub Pages, password)

The same page can be hosted without sending files around: the app is public, the data and the labels stay in a private repo.

```sh
export LABEL_PASSWORD='…'        # given to the labeller; long and random
export LABEL_GITHUB_TOKEN='github_pat_…'
uv run answer-eval label-publish --run-id answers-idcc22-j \
  --repo <owner>/<private-data-repo> --out <dir> --annotator <name>   # [--data-path --seed --title --models --force]
```

- **What goes where.**
  - `<dir>/page/index.html` → the root of a **public** repo served by GitHub Pages (Settings → Pages → Deploy from a branch, `main`, `/`). It holds the app and a vault, nothing else: no question, no answer, no model name.
  - `<dir>/data/data.json` → `data.json` (or `--data-path`) in the **private** data repo: the questions, the blinded answers, the sources and the criteria.
  - `labelling/key.json` stays in the run directory, in neither repo (`label-publish` refuses an `--out` that would hold it).
- **The token.** GitHub → Settings → Developer settings → Fine-grained tokens → Generate:
  - Repository access: *Only select repositories*, the data repo only.
  - Permissions: *Contents: Read and write* (Metadata: read-only is added automatically), nothing else.
  - An expiry date just after the labelling campaign. Revoke it when done.
- **The vault.** The token is encrypted with AES-256-GCM; the key is PBKDF2-HMAC-SHA256 of the password (NFC), with a random 16-byte salt and 600 000 iterations; the IV is random (12 bytes). The repo and the data path are stored in clear. `LABEL_PASSWORD` and `LABEL_GITHUB_TOKEN` are read from the environment (or `eval/.env`) and never printed.
- **In the browser.** The labeller types the password. The page decrypts the token (WebCrypto), reads `data.json` through the GitHub contents API and keeps the token in memory only: a reload asks for the password again.
  - Labels are saved in the browser as in the local page, and committed to `labels.json` in the data repo (one labeller) 15 s after the last change, when moving to another question, and with the "Enregistrer" button. The header shows the state (enregistré, modifications non enregistrées, enregistrement…, erreur).
  - On opening, the page merges the repo file with the browser's copy: a label changed in this browser since its last successful save keeps the browser's value; any other label takes the repo's value (the last save, possibly from another computer). If the file does not exist yet, the browser's copy is kept as is.
  - If the file changed in between (sha conflict, another tab or computer), the page reads it again, merges it the same way and retries once; a failed save stays pending until the next change or "Enregistrer".
  - The file: `{"format": "answers-labelling/1", "dataset_id", "labels": {"07-C": {"correct_en_droit": "Oui", …, "comment", "flag", "seconds"}, "07-Q": {"sources_suffisantes": "Non", "comment"}}}`, started labels only. A file made for another build of the page (another `dataset_id`) is ignored by the page and refused by the import: the same `label_id` may name another answer there.
- **Getting the labels.** `LABEL_GITHUB_TOKEN=… uv run answer-eval label-import --run-id answers-idcc22-j` reads `labels.json` from the repo `label-publish` wrote to (`labelling/publish.json`; `--repo` to override), keeps a copy in `labelling/repo-labels.json`, and imports it under the name given to `label-publish --annotator` (default `expert`; `--annotator` to override). The name never appears on the page. Then `report`.
- **Security limits.**
  - Anyone with the password (and the page's URL) gets a token that can read and write the data repo: the questions, the answers and the labels. Share the password like the data itself.
  - The public repo holds only the ciphertext, which can be attacked offline: use a long random password (at least 5 random words or 16 random characters). 600 000 PBKDF2 iterations slow guessing but don't save a weak password.
  - The token is scoped to one repo and expires; every save is a commit, so the git history keeps all versions of the labels.
  - The page needs `https` (GitHub Pages) or `localhost`: WebCrypto is not available elsewhere.

## Known production issues (to fix in the API)

- **Zero-padded IDCC (seen 2026-10-20, still there 2026-10-28).** The web sends `agreement.id`, which is zero-padded ("0029", "0953"), to `/idcc/search`.
  - Contributions are indexed with the padded IDCC ("0292") and conventions with the unpadded one ("292").
  - When a CC has no contribution, the fallback in `api/srdt_analysis/api/main.py` (`get_contributions_idcc`) searches the conventions with the padded value and finds nothing. These CCs therefore get **no CC extract in production**: in this eval, IDCC 0029 (q_c2de0798) and 0953 (q_6747dba4).
  - The eval reproduces it on purpose. Fix: normalise the IDCC (strip leading zeros) before the conventions search, then rebuild the contexts under a new run id.
