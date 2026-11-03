# Manual labelling of run `answers-idcc22-j`

A blind human evaluation of the answers that 4 models give to the 22 IDCC questions.
Every model gets the exact prompt the web sends to `/api/generate`, with the sources
held fixed. One labeller, David, grades every answer and judges whether the sources
were enough to answer.

How the tools work in general (export, publish, import) is in [README.md](README.md).
This page describes this campaign only.

| | |
|---|---|
| Run | `eval/runs/answers-idcc22-j` (local, git-ignored) |
| Page build | dataset `69c925e0cb`, seed 0, built 2026-10-29 |
| Labeller | David (`--annotator David`) |
| Labels | 88 answers (22 questions × 4 models) + 22 sources labels |
| Status | published; labelling in progress |

## What is being labelled

**Questions.** The 22 questions of the `idcc22` set. They are anonymised real user
questions, which stay out of this public repo; 18 of them name a collective agreement
(IDCC).

**Prompt and sources.** These are frozen in `contexts.jsonl` and identical for all
models; see the table in [README.md](README.md#what-the-prompt-contains).
- Template: `prompts/web-v2.0.json`, exported from `web/src/prompts`.
- Fiches: the documents the llama labeller graded ≥ 1 in the retrieval eval, at most 10.
- Code du travail and CC extracts: retrieved live on 2026-10-20, as production does.
  Case law: retrieved on 2026-10-28.
- Case law: 19 decisions were kept by the production filter, in 8 questions.

**Models.** All run at temperature 0.3 (production's value), with no output cap:

| Model | Host | Why it is here |
|---|---|---|
| mistral-large-latest | Mistral API | Production: the baseline |
| mistral-medium-3.5 | Albert (DINUM) | Same family, government hosting |
| glm-5.2 | Scaleway (ministry LiteLLM gateway) | Large open model that reasons before answering; sovereign cloud |
| qwen3.5-397b-a17b | Scaleway (ministry LiteLLM gateway) | Largest open model on Scaleway; replaced gpt-oss-120b |

**Left out of the labelling:**
- **gpt-oss-120b** (Albert) was generated and judged, but replaced by qwen3.5 before
  labelling. It ignores the answer structure and the citation format: 7 answers have
  no quote, 61 % of its quotes are word for word, and it gives 5 links that are not
  in its prompt (see "Signals before labelling" below). Its answers stay in
  `answers.jsonl`.
- **Reasoning mode for mistral-medium-3.5:** neither Albert nor Scaleway enables it
  (the parameters are accepted and ignored), and the comparison avoids the Mistral
  API for candidate models. See `config/generators-variants.toml`.

## What David answers

For each answer, Oui/Non on three criteria, rated independently, plus an optional
comment and a "to review" flag:
- **correct en droit**: no legal error, and rules that apply to the situation;
- **suffisant**: answers every part of the question and gives what the user needs to act;
- **intelligible**: understandable by a non-lawyer.

For each question, one label: **"Sources suffisantes pour répondre ?"** It judges the
retrieval, not the answers: could someone with only these extracts give the right
answer, including on the CC point? The comment says what is missing.

- **Criterion definitions:** they come from `prompts/v1/*.fr.md`, the LLM judge's
  definitions, so the human and the judge grade the same thing. They are drafts,
  inferred from the column names of the 18-question human dataset, not an annotation
  guideline.
- **Answer order:** A–D is shuffled per question. No model or host name appears on
  the page.

## Setup

| What | Where | Visibility |
|---|---|---|
| The page (app + encrypted token, no data) | page repo, `index.html`, GitHub Pages | public |
| Questions, blinded answers, sources | `rmelisson/label-srdt-data`, `data.json` | private |
| David's labels | `rmelisson/label-srdt-data`, `labels.json` (one commit per save) | private |
| **Key: label → model** | `eval/runs/answers-idcc22-j/labelling/key.json` | **local only** |
| Repo and labeller name for the import | `eval/runs/answers-idcc22-j/labelling/publish.json` | local only |
| Built files, before push | `eval/runs/answers-idcc22-j/publish/{page,data}/` | local only |

**Access:**
- David opens the page and types the password. The page decrypts a fine-grained
  GitHub token (Contents read/write on the data repo only, with an expiry date), reads
  `data.json` and saves `labels.json` in the same repo.
- Labels are saved 15 s after a change, when he moves to another question, and with
  "Enregistrer".
- **Secrets:** the password and the token live only in `eval/.env` (`LABEL_PASSWORD`,
  `LABEL_GITHUB_TOKEN`). The password reaches David through a separate channel from
  the link.

**The key.** `key.json` maps every label (`07-C`, `07-Q`) to its model and question,
and holds a fingerprint of each answer.
- Never put it in either repo: David's token can read the data repo.
- Keep a copy outside `runs/`. Should it be lost, running the same `label-publish`
  again on the same answers gives the same key (the shuffle is seeded); dataset id
  `69c925e0cb` confirms the match.
- `labelling/answers-labelling.html` in the run is an older single-file page (with
  gpt-oss, another order): don't use it.

## Steps

- [x] Generate the answers and the judge verdicts (2026-10-28/29)
- [x] Build the page: `label-publish --repo rmelisson/label-srdt-data --annotator David`
- [x] Create both repos and the token
- [ ] Push `data.json` (data repo) and `index.html` (page repo); enable Pages
- [ ] Test before sending: open the page, rate one answer, "Enregistrer", check the
      `labels.json` commit, then delete that file and the browser's site data
- [ ] Send David the link, and the password separately
- [ ] Import and report (below)
- [ ] Revoke the token when the campaign is over

**Don't rebuild the page during the campaign.** A new build (other models, other
answers, another seed) changes the dataset id. The page then ignores David's
`labels.json`, and the import refuses it, because the same label (`07-C`) may name
another answer. If a rebuild is unavoidable, start a new campaign.

## Getting the results

From `eval/`, with `LABEL_GITHUB_TOKEN` in `.env`. Both commands can be run at any
time, also mid-campaign:

```sh
uv run answer-eval label-import --run-id answers-idcc22-j   # pulls labels.json, decodes it with key.json
uv run answer-eval report --run-id answers-idcc22-j
```

`label-import` writes, in `runs/answers-idcc22-j/labelling/`:
- `human-David.jsonl` (answers) and `question-labels-David.jsonl` (sources);
- `dataset-David.json`, in the format of the 18-question human dataset;
- `repo-labels.json`, a copy of the file it read.

Answers rated on only some criteria are listed and left out.

**Where to look:**
- **`report.md`:**
  - "Human David": share of Oui per model and criterion, and "all three". This is the
    main result.
  - "Human: sources sufficient": the share of questions answerable from their sources,
    then each model's refusals on questions with and without sufficient sources. A
    refusal despite sufficient sources is the model's failure; without them, the
    retrieval's.
- **`answers.md`:** question by question, the 4 answers with David's verdicts and
  comments, the judges' verdicts and the sources verdict. Start with flagged answers
  and questions where the models disagree.
- **`per_answer.csv`:** one row per answer and judge, for filtering and sorting.

**LLM judges against David.** Their agreement (κ per judge and criterion) tells
whether a judge could replace a human on later runs:

```sh
uv run judge-eval run --dataset runs/answers-idcc22-j/labelling/dataset-David.json \
  --models config/models.toml --only scaleway/scaleway/llama-3.3-70b-instruct,albert/gemma-4-31b-it \
  --baselines --run-id judges-vs-david
uv run judge-eval report --dataset runs/answers-idcc22-j/labelling/dataset-David.json --run-id judges-vs-david
```

## Signals before labelling

These are what the human labels will confirm or contradict. All figures are from
`report.md` (2026-10-29).

| Model | Quotes word for word | Links not in the prompt | CC refusals (of 18) | Median latency |
|---|---|---|---|---|
| mistral-large (prod) | 37/60 (62 %) | 16, in 7 answers | 13 | 21 s |
| mistral-medium-3.5 | 44/59 (75 %) | 1 | 14 | 21 s |
| glm-5.2 | 85/97 (88 %) | 0 | 11 | 85 s |
| qwen3.5-397b | 102/110 (93 %) | 0 | 14 | 31 s |
| *gpt-oss-120b (not labelled)* | 37/61 (61 %) | 5 | 10 | 16 s |

- **Citations:** checked mechanically (`answer_eval/citations.py`). Production's
  mistral-large builds Légifrance article URLs from LEGIARTI ids, which the prompt
  forbids. The prompt only gives section-level URLs, so these links reach users
  unchecked.
- **LLM judges:** gemma-4-31b and llama-3.3-70b judged all 110 answers, but they give
  the same verdict on only 63–76 % of answers and don't rank the models the same way.
  They see neither the sources nor a real guideline: treat their scores as noise until
  compared with David.

## Known limits

- **One answer per model and question,** at temperature 0.3. With 22 questions, a gap
  of 1–2 answers (5–10 points) can be chance.
- **Model and host are confounded.** glm-5.2 on Scaleway is capped at 16,384 output
  tokens, hidden reasoning included. Its answer to q_16c8ef09 is cut mid-sentence and
  labelled as is.
- **CC refusals** ("je ne dispose pas d'information spécifique sur votre convention")
  happen 11–14 times per model. They mostly follow the retrieved CC extracts, so the
  sources label is what separates the models from the retrieval here.
- **IDCC zero-padding bug (production):** CC extracts are searched with the padded
  IDCC, so the questions on IDCC 0029 and 0953 get none. It is reproduced here on
  purpose; see "Known production issues" in [README.md](README.md).
- **Draft criteria:** the definitions are not a validated guideline. The judge and
  David at least read the same text.
