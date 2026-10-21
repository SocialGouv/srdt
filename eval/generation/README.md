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
| Jurisprudence | None (as when the user unticks it in the web) |

The user message is the anonymised question, sent as is.

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
