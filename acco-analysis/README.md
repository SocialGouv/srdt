# acco-analysis

Temporary analysis module: what do the **heat clauses** (canicule, fortes chaleurs…) of French
**company agreements (ACCO, Légifrance)** actually say, and how many companies say it?

It finds the passages about heat, keeps the real clauses, codes each one with a shared
codebook (two LLMs), counts **per agreement**, and groups the clauses into recurring
**nuances** (code `flavours`) inside each family. Outputs are a Markdown report, CSV tables and
a local, self-contained HTML page.

- Own `uv` project, not part of the API or the ingestion pipeline. It imports `ingestion/`
  read-only (`split_sections`, `LocalStore`) so its sections are the same as the index chunks.
- **Everything derived from the agreements stays local**: `out/` is gitignored (public repo).
- Nothing here is committed yet. Do not commit unless asked.
- Comments and code are English; prompts, codebook labels, reports and the page are French
  (the passages are French). In the code the word is `flavours`; in every French text the
  user-facing word is **« nuances »** (never « saveurs »).

## Setup

```bash
cd acco-analysis
uv sync
cp .env.example .env     # ALBERT_API_KEY; falls back to ../ingestion/.env
uv run acco-analysis --help
uv run pytest && uv run ruff check . && uv run pyright     # 121 tests, all clean
```

Settings (`settings.py`): Albert endpoint and key, embedding model (`BAAI/bge-m3`), main chat
model `ACCO_LLM_MODEL` (default `mistral-medium-3-5`), snapshot store (`SNAPSHOT_LOCAL_DIR`,
default `../ingestion/snapshots`).

**Input**: the latest `acco` snapshot written by the ingestion CLI, e.g.
`ingest fetch acco --from-dir /Users/remi/tmp/legi-ae/results/accords`. Current snapshot
`20261028-local.5d6dc65b`: 2,399 agreements, signed 2017–2026 (2026 partial). The source
itself (`ingestion/src/ingestion/sources/accords.py`, `config/acco.toml`) is documented in
`ingestion/README.md`.

`typst` (`brew install typst`) is only needed for `report-pdf`; its tests skip without it.

**Models**: the main model codes everything, a second model (`gemma-4-31b-it`) re-codes
everything for the agreement figures. Both are called through Albert (OpenAI-compatible).
Every call (embeddings and chat) is **cached on disk** in `out/cache` by model + prompt, so
re-running a stage is free; **changing a prompt re-runs that stage's calls** (2,731 passages
x 2 models for coding is about 80 minutes; the 40 nuance descriptions take a few minutes).

## The pipeline

Run in this order. Each command reads files of `out/` and writes new ones.

| # | Command | LLM | Reads | Writes | Module |
|---|---|---|---|---|---|
| 1 | `extract` | no | snapshot | `passages.jsonl` | `extract.py` |
| 2 | `filter` | 2 models | passages | `relevance.jsonl` | `relevance.py` |
| 2b | `sample`, `queue`, `import-labels`, `evaluate` | no | | `label_sample.csv`, `label_queue.json` | `labelling.py` |
| 3 | `cluster` | embeddings | kept passages | `embeddings.npy`, `clusters.json` | `cluster.py` |
| 4 | `label` | main | clusters | `labels.json` | `label.py` |
| 5 | `report` | no | clusters, labels (+ families) | `clauses.json/.md` | `report.py` |
| 4b | `merge` | main | `clauses.json` | `families.json` | `merge.py` |
| 6 | `open-code` (once, to write the codebook) | main | families | `open_coding.jsonl/.md` | `coding.py` |
| 7 | `code` | 2 models | kept passages | `coding.jsonl` | `coding.py`, `codebook.py` |
| 7b | `code-queue`, `code-import`, `code-evaluate` | no | pilot | `coding_check.html`, `coding_labels.json`, `coding_eval.json` | `coding_labelling.py` |
| 8 | `rollup` | no | coding, embeddings | `profiles.jsonl`, `templates.json` | `rollup.py` |
| 9 | `metrics` | no | profiles, coding | `metrics.json/.md`, `metrics_*.csv` | `metrics.py`, `metrics_report.py` |
| 10 | `flavours [--no-describe]` | main | profiles, coding | `flavours.json/.md/.csv` | `flavours.py`, `flavours_report.py` |
| 11 | `site` | no | flavours, metrics, profiles | `flavours.html` | `site.py`, `flavours_site.html` |
| 11b | `accords [--encrypt] [--no-report]` | no | snapshot, kept passages, flavours, profiles, the report inputs (needs typst) | `site/` or `site-enc/` | `accords_site.py`, `crypto_site.py`, `pages/`, `report_style_web.typ` |
| 11c | `publish` | no | `site-enc/` | the Pages repo clone (no git) | `accords_site.sync_to_repo` |
| 12 | `report-pdf` | no | metrics, passages, coding, relevance, snapshot (company and year of the quotes) | `report.pdf`, `report/` (data + template copy) | `report_pdf.py`, `report_facts.py`, `report.typ`, `report_style.typ` |
| 12b | `report-polish` | main | `report.typ`, the report data | `report-polished.typ`, `report-polished.pdf`, `report-polished-notes.md` | `report_polish.py` |
| 12c | `note-rapprochement [--no-polish]` | main | the report data, `note_rapprochement.typ` | `note-rapprochement.pdf`, `.typ`, `-notes.md` | `note_rapprochement.py`, `report_facts.recent_facts` |

Stages 8, 9, 11, 11b, 11c and 12 take seconds (12b makes a few Albert calls) and call no model. `flavours --no-describe` counts the
nuances without naming them (also free), which is how to tune the discovery.

**Order pitfall**: after `label` the order is `report` -> `merge` -> `report` (`merge` reads
the `clauses.json` that `report` writes; the second `report` adds the families).

**Invariant**: `embeddings.npy`, `coding.jsonl` and the passage order all follow `_kept()` in
`cli.py` (passages labelled specific or generic, in `passages.jsonl` order). If the filter
changes, rerun `cluster` (re-embeds) before `rollup`, and rerun `code` (the cache makes
unchanged passages free).

### What to rerun when something changes

| Change | Rerun from |
|---|---|
| New agreements in the snapshot | `extract` and everything after (caches make unchanged calls free); `rollup`, `metrics`, `flavours`, `site` all recompute their denominators from the data |
| `relevance.SYSTEM` (filter prompt) | `filter`, `cluster`, `label`, `report`, `merge`, `report`, `code`, then 8 to 11 |
| `codebook.py` (definitions, codes) or `coding.py` prompt | `code`, then 8 to 11 |
| Family definition (`FAMILIES` in `codebook.py`) | 8 to 11 (no model call except nuance descriptions) |
| Discovery rules in `flavours.py` (weights, thresholds) | 10 and 11 |
| `flavours.SYSTEM` (description prompt) | 10 (40 calls) and 11 |
| Page only (`flavours_site.html`, `site.py`) | 11, then 11b (the published copy embeds the page) |
| Agreement page (`pages/accord.html`, `accords_site.py`) | 11b, then 11c |
| Report wording, quotes or layout (`report.typ`, `report_style.typ`, `report_pdf.py`) | 12 (after any rerun of 8 to 10, and reread the prose) |
| `extract.py` (passages) | `extract` rewrites `passages.jsonl`; ids and text must not change (compare with the old file), then 11b |

## Key design decisions (and why)

- **The counting unit is the agreement, never the passage.** 2,731 kept passages sit in 2,085
  agreements (up to 9 each). All figures are "how many companies have X".
- **Two readings of every figure, no single truth.** `strict` = the code given by **both**
  models (lower bound); `loose` = by **either** (upper bound). The gap is the reliability
  signal. A code is flagged `model_dependent` when loose >= 10 and strict < 0.6 x loose.
  Single-valued dimensions take the value when both agree, else `models_disagree`; missing is
  `unknown`. No coding is validated by hand yet.
- **Denominator**: agreements with a heat clause (loose 2,064 / strict 2,009 of 2,399
  collected; 335 have none). Wilson 95 % intervals. Groups under 10 agreements get counts but
  no percentage (`MIN_CELL`).
- **One shared codebook** (`codebook.py`) feeds the prompt, the validation of answers and the
  families, so a code cannot exist in one and not the other. Codes are English identifiers,
  labels and definitions French. Dimensions: `measures` (multi), `triggers` (multi),
  `initiative`, `pay`, `strength` (single), `scope`, `procedure` (multi), plus `numbers`
  (kind/value pairs) and `about_heat`.
- **Families are views over measure codes**, not clusters: hours, rest, telework, prevention,
  stoppage, pay (a passage can be in several), plus the residual `reference_or_other`. The 15
  k-means clusters and 5 families from the first pass only appear as a cross-check table in
  the metrics.
- **Evidence is verified.** The model gives a short quote per measure; it is kept only if it
  occurs verbatim in the passage (`label.verbatim`, tolerant to case, spacing, accents).
- **Templates**: the same clause signed by several companies. Detected by normalised-text hash
  plus cosine >= 0.95 on the embeddings between *different* agreements (union-find). 346
  groups; 934 agreements (45 %) sit in one. Nothing is deleted; every count has a "collapsed"
  variant counting a template once.
- **Nuances (flavours): counts come from the codes, the LLM only names and describes.**
  Greedy partition of a family's agreements on strict profiles: items are `dimension:code`
  over measures + triggers + pay (telework also initiative/procedure/scope); score = support x
  specificity^2 (named triggers and pay weigh 2, others 1); the best combination takes its
  agreements, then the search goes on with the rest, so an agreement is in **one** nuance
  (the "loose" column is an overlapping upper bound). Min support `max(10, 3 % of family)`,
  max 10 per family, constant items (>= 95 %) excluded, bare `canicule_unqualified` gives way
  to a named trigger, vigilance yellow/orange/red merge into `vigilance_coloured`, residual
  family skipped. The model sees <= 8 extracts (central ones, one per template or agreement,
  plus a few random) and the counted facts.
- **Citations**: 3 to 4 per nuance when the data allows. The prompt asks for 4; if fewer than 3
  pass the verbatim check there is one retry, then the best heat sentence of the other shown
  extracts is added (copied from the text, not picked by the model).
- **The page is a local file, not a Claude artifact**: data embedded as JSON in
  `<script type="application/json" id="data">`, vanilla JS (`h()`/`s()` DOM helpers), no
  network, light/dark tokens, state in `localStorage` key `acco-flavours-v1`.

## Agreement viewer and publishing (11b, 11c)

`accords` writes a small **site**: the nuances page plus one page per agreement placed in a
nuance or in a family's « autres combinaisons » (1,868 of 2,399), so a quote or a nuance card leads to the clause **in its agreement**
(« Lire l'accord » on each quote, a collapsible « Accords (n) » list per card, badges and a
back link on the agreement page). The agreement page shows the cleaned section lines the
models read (not the byte-exact original), the coded passages on a tinted background and the
quote shown on the card in `<mark>`; every one of the 144 quotes is located.

- **Files** (`out/site/`, plain, for local preview: `python3 -m http.server -d out/site`
  then open `index.html`; `file://` does not work, the pages `fetch` their data):
  public shell `index.html`, `accord.html`, `gate.js` (no content), `manifest.json`
  (`encrypted`, PBKDF2 `salt`, `iterations`), and `data/`: `app.dat` (the nuances page) and
  `<key>.dat` per agreement, key = salted sha256 of the agreement id (so an encrypted
  site does not list which agreements are in). Page data is built by
  `accords_site.build_agreement`; links need the keys, so `site.build_data(..., salt)` is
  called by `accords` (the standalone `out/flavours.html` of `site` has no such links).
- **Encrypted** (`accords --encrypt` -> `out/site-enc/`, 18 MB, the plain one is 65 MB):
  every data file is `iv + AES-256-GCM(gzip(data))`, key = PBKDF2-SHA256 (600,000
  iterations) of the password and the manifest salt, one key per build, one random IV per
  file (`crypto_site.py`). `gate.js` asks for the password, derives the key once, keeps it
  in `sessionStorage` (same tab: no second prompt; a new tab asks again), decrypts with
  WebCrypto and `DecompressionStream`. The password comes from `ACCO_SITE_PASSWORD` or a
  prompt, is never written, and a build warns under 20 characters.
- **Publishing**: a **separate public repo** serves GitHub Pages. `publish --repo <clone>`
  (or `ACCO_PAGES_REPO`) replaces the clone's content with `out/site-enc/` and adds
  `.nojekyll`; it refuses a plain site and never runs git. Then, in the clone,
  `git add -A && git commit --amend -m site && git push --force` keeps one commit (the very
  first commit is a normal one).
- **Threat model**: the repo is public, so the ciphertext is downloadable by anyone and the
  password is the only protection: use a long random passphrase (6+ words). There is no
  revocation: whoever has a copy and the password reads that version; changing the password
  means rebuilding and force-pushing (GitHub may keep old commits reachable by their hash
  for a while). The agreements themselves are public on Légifrance; what is protected is the
  derived analysis. This is a deliberate exception to « everything derived stays local ».
- `gate.js` and `crypto_site.py` share a format: `tests/test_crypto_site.py` has the real
  `gate.js` decrypt a file written by Python (needs `node`, skipped otherwise).

**The analysis note is a page of the site** (`report.html`, encrypted like the rest, linked
as « Note d'analyse » from the nuances page). It is the same `report.typ` as the PDF, built with
`report_style_web.typ` through Typst's HTML export (`typst compile --features html`) and styled
by the CSS of `pages/report.html`. Typst marks that export as experimental: a new Typst version
can change it, and `tests/test_report_pdf.py::test_web_report_is_semantic_html...` fails first.
The quotes link to the agreement pages with relative links built from the **salt of the site
being built**, so the page never has stale links (unlike the PDF, which uses the published
build). `accords --no-report` leaves it out (no typst needed). Publish as usual: `accords
--encrypt`, then `publish`, then the git commands.


## Outputs worth knowing

- `coding.jsonl`: one row per passage `{id, agreement_id, main, check}`; each side has
  `about_heat`, the dimensions (measures carry `code`, `quote`, `verified`), `numbers`,
  `families`. Passages a model failed to code twice are left out and reported by `code`.
- `profiles.jsonl`: one row per agreement and mode (`strict`/`loose`): passages, `passage_ids`,
  `families`, every dimension as a sorted list, `numbers`, `template`.
- `templates.json`: `{passage id: template group}`.
- `metrics.json/.md`: dataset block, families, per-code tables (strict/loose/intervals/
  collapsed), breakdowns by year, sector, IDCC, co-occurrence, family overlap, quantities
  (temperatures, durations, amounts), cluster cross-checks, and `problems` (consistency
  checks that must be empty). CSVs: `metrics_codes`, `_by_year`, `_by_sector`, `_by_idcc`,
  `_cooccurrence`.
- `flavours.json/.md/.csv`: per family `strict`, `loose`, `constant` items, `min_support`,
  `flavours` (codes, counts, Wilson interval, collapsed, member agreements, distributions,
  years, top sectors, shown passage ids, name, description, variations, verified quotes) and
  `other` (agreements outside any nuance).
- `report.pdf`: a 7-page French **analysis note** (table of contents first, internal
  audience): what the clauses mean rather than how many there are. Two ways heat appears
  (a dedicated scheme vs one case in a general clause), which sectors write which (NAF sections
  from the APE code, `Agreement.ape`; landscaping, IDCC 7018, is a template-driven case), what triggers a scheme and what it
  provides, heat used to loosen rules (same-day planning, recovery of lost hours, rest
  derogations, exceptional telework), who decides / how binding / who pays, what the
  clauses leave unsaid, reservations. The prose is hand-written in `report.typ` from a
  reading of the extracts; every figure comes from `report_pdf.build_data` /
  `report_facts.compute` (French-formatted into `out/report/data.json`) and every quoted
  clause is checked word for word against its passage (`out/quotes.json`, keys in `QUOTE_KEYS` of
  `report_pdf.py`: kept out of the repo; the build fails if one is gone or the file is missing). Rerunning after new data refreshes the numbers, **not the
  claims**: reread the prose. Holds agreement quotes, so it stays in `out/`.
- `note-rapprochement.pdf`: a 3-page note that sets this analysis beside another study (the
  DS2/DS1 note on climate adaptation): periods and units compared, what converges (table of the
  recent agreements), four apparent gaps with their reading, how to cite both. Same machinery
  as the report (prose in `note_rapprochement.typ`, figures from `report_facts.recent_facts`,
  polish through `report_polish.polish` with its own prompt). The other note's figures are
  typed in the template (they are quoted, not computed): edit them there if that note changes.
  The model's rewrite once merged two figures of different scopes: **read the PDF against the
  draft** (`note_rapprochement.typ` in `src/`).
- **Report look**: the prose is in `report.typ` and knows nothing about typography; the look
  is `report_style.typ` (sans, numbered section tabs, panels, quote cards), copied next to it as
  `style.typ` at build time. It exports `report`, `figures`, `quote-block`, `lead` and
  `title-block`; labels shown to the reader stay in `report.typ`.
- **Links to the UI**: each quote card has « Légifrance » and « Lire l'accord » (the agreement
  page of the published UI, at the section of the quote); the footer links to the UI home. The
  agreement files are named by a salted hash, so the links come from `out/site-enc/manifest.json`
  (the **published** build: rebuild the site and the links change, so republish, then rebuild
  the PDF) and `ACCO_SITE_URL`. Without either, or for an agreement that has no page, the
  card keeps its Légifrance link only; `report-pdf` says so.
- `report-polished.typ/.pdf`, `report-polished-notes.md`: `report-polish` has the main model
  (Albert) improve the French of the prose only. Figures (`#f.<name>`) and quotes
  (`#q("<key>")`) must come back untouched: `report_polish.check` rejects an answer that
  drops or adds one, adds a digit, adds a strong word ("requis", "toujours", "seul"...), changes
  the headings or grows the text, and the rejected answer is sent back to be corrected (4
  attempts). It **never overwrites `report.typ`**: compare, then copy it over if it is better.
  Read the notes file (the model's list of shaky claims) and the prose: the checks catch
  structure and strengthening, not every shift of meaning (a rewrite once turned "accord avec
  les représentants" into "initiative des représentants").
- `flavours.html`: overview tab (corpus figures, strict-loose family bars, per-year small
  multiples; **year, sector and "a template counts once" filters** work client-side) and one
  tab per family with nuance cards. The overview recomputes from all 2,399 collected
  agreements (`D.all` rows `[year, sector, strictMask, looseMask]`, bits 0-5 = family order,
  bit 6 = has a heat clause). "A template counts once" applies to the family tabs only, and
  the distribution bars on cards are static (not filtered). Quotes on a card are limited to
  agreements passing the filters, so a card can show fewer than 3 under a narrow filter.

## State of the results (snapshot 20261028, as of 2026-11-02)

- Filter (hand-labelled 100 passages, rules refined once): mistral acc 0.77 (precision 0.875,
  recall 0.926), gemma 0.78 (0.908, 0.868); the models agree on 87.9 % of passages. 3,474
  passages extracted, 2,731 kept.
- Closed coding: 2,731 passages x 2 models. Measure kappa high for telework, water, cooling,
  extra_breaks, protective_gear (>= 0.9); weak for production_stop (0.42), reference_only
  (0.40), other (0.26), action_plan (0.55), shorter_day (0.52); initiative 0.47.
- Families (agreements, strict / loose, of 2,064): hours 729 / 866, telework 574 / 602,
  prevention 580 / 743, stoppage 212 / 365, pay 82 / 113, rest 37 / 60.
- 40 nuances over 6 families (hours 9, rest 2, telework 8, prevention 10, stoppage 6, pay 5
  in the latest run; 1,671 agreements placed in one, 1,868 with the « autres combinaisons »).
  Names and descriptions are written by the model and **not validated by hand**.

## Known limits and issues

1. **Weak codes**: `event_list` vs `canicule_unqualified` is an unresolved codebook decision
   (both models code `event_list` on ~35 % of passages while the user ticked it 0 / 20;
   read the two together); `production_stop`, `action_plan`, `procedure` (`written_note`,
   `fixed_duration`, `notice_period`), `initiative`, `reference_only`, `other` are
   over- or inconsistently coded. Per-dimension scores are in `coding_eval.json` and
   `metrics.json` (`model_dependent`).
2. **Hand labels are set aside.** The user's 20 hand-coded passages
   (`coding_labels.json`, `coding_eval.json`) were deliberately not used for the full run
   ("ignore my labels for now"). Re-scoring is `code-evaluate`; the user left single-choice
   dimensions blank on some passages, which counts as errors.
3. **Nuance names are not guaranteed unique**: two names appear twice in the latest run
   (hours #1 and #8 "horaires aménagés canicule sans seuil", prevention
   "rafraîchissement et eau en canicule"). The model is given the sibling codes but not the
   sibling names; a uniqueness check or a retry would fix it. Hours #8 is the broad
   "schedule shift only" bucket and its name should say "other".
4. **Passage length**: a passage is the whole section that holds the heat term, or a window of
   a few lines around it when the section exceeds 3,000 characters (`extract.py`:
   `MAX_SECTION_CHARS`, `LINES_BEFORE/AFTER`). A window can lose a condition or an exception
   stated nearby (scope, procedure, initiative are the weakest dimensions). Not measured yet:
   compare model agreement on windowed vs whole-section passages (`passages.jsonl` has the
   `windowed` flag). Nuance descriptions only show the first 900 characters of each extract.
5. **Prevention is a bag of measures**: 224 of 580 agreements are outside any nuance.
6. **Recall is capped by the extractor**: only text around `canicule`, `chaleur` and variants
   is read ("températures élevées" alone is missed), so the figures are floors and describe
   companies that frame heat, not French companies. 38 heat agreements are truncated (the API
   cuts texts at about 98,000 characters; 35 agreements come from docx/odt).
7. **Browser checks are partial.** `out/flavours.html` was never looked at (it was
   smoke-tested under node with a DOM stub). The agreement page and the encrypted flow
   (prompt, wrong password, decrypt, `document.write` of the nuances page, quote links) were
   exercised in headless Chrome over `http.server` and the agreement page was seen at
   desktop width and at 390 px in dark mode; not checked: light theme and Safari/Firefox,
   and the real GitHub Pages deployment.

## Roadmap (nothing requested yet, ordered by value)

1. Open `out/flavours.html` in a browser, report layout problems.
2. Decide `event_list` vs `canicule_unqualified`, fix the weak definitions, re-score against
   the 20 hand labels (and code the other 20 of the pilot), rerun `code` and 8 to 11. This is
   what moves the numbers most.
3. Validate nuance names and descriptions by hand, make names unique.
4. Measure the effect of windowed passages (limit 4); widen the window or keep the whole
   section if agreement is lower there.
5. Split the prevention family or code its missing dimension.
6. Hand validation set larger than 20, drawn after the rules are fixed (the 100 filter labels
   were used to design the filter prompt, so they are no longer a fair test).
7. Production path (to the shared search index): the real Albert embedding run into `chunks_acco`, then merging the source
   into the shared index (api `core/constants.py`, `core/models.py`, empty `OPTIONAL_SOURCES`
   in `ingestion/contract.py`; `api/tests/test_chunk_schema.py` asserts 8 examples and there
   are now 9). `api/` is the user's active area: do not touch it without asking.
8. Optional: delete the old private labelling artifact on claude.ai (holds passage excerpts).

## How to extend

- **A new code**: add it to the dimension in `codebook.py` (code, French label, definition);
  `render_codebook`, the validation and the metrics tables pick it up. Add it to a family in
  `FAMILIES` if it is a measure. Rerun from `code`. Labels shown in reports come from
  `metrics.LABELS`, built from the codebook.
- **A new dimension**: add a `Dimension`, list it in `DIMENSIONS`, handle it in
  `coding.clean_closed`, `rollup.MULTI/SINGLE`, `flavours.DESCRIBED` (and `DISCOVERY` if it
  should tell nuances apart), `metrics` and `metrics_report`.
- **A new family**: entry in `FAMILIES`. The page reads the families order from the data, but
  the filter masks use bit position = family order (6 bits + the heat bit), so keep
  `site.build_data` and `HEAT` in `flavours_site.html` in step.
- **A new metric**: a pure function in `metrics.py` returning plain data, added in `build()`,
  rendered in `metrics_report.py`. Add a consistency check to `consistency_problems`. Tests in
  `tests/test_metrics.py` build small synthetic codings with `test_rollup.coded/row`.
- **A new breakdown** (by nature, union, size…): `Agreement` in `corpus.py` already holds
  `nature`, `themes`, `unions`, `idcc`, `sector`, `signed`; follow `metrics.breakdown`.
- **Tuning the nuances**: `flavours --no-describe` prints the counts per family for free; adjust
  `MIN_SHARE`, `MAX_FLAVOURS`, `SPECIFIC_TRIGGERS`, `weight`, `DISCOVERY_BY_FAMILY`.
- **More agreements**: nothing is hard-coded to 2,399 / 2,085 / 2,731. Refetch the snapshot and
  rerun; reports print the snapshot id so two runs can be compared.

## Conventions and pitfalls

- Tests: `uv run pytest` (pure functions, no network; `FakeAlbert`-style stubs in
  `test_flavours.py`). Ruff line length 88; long French prompt files have per-file `E501`
  ignores in `pyproject.toml`. Pyright is strict about `Mapping` vs `dict` variance.
- `chat_json` is temperature 0 and cached: identical prompts give identical answers, so any
  change in a prompt (even a space) is a cache miss.
- A backgrounded `command; echo exit` reports the wrapper's exit code: check the tail of the
  log (`out/coding_run.log`) and the output file instead.
- Models sometimes answer per section with ids like `<id>_6-7` (merged by `coding._owner` and
  `_merge_items`) or return truncated JSON (caught, retried alone with `max_tokens=8000`,
  leftovers dropped and reported).
- Do not `git stash -u` while a labelling or coding job appends to untracked files in `out/`.
- BSD `sed` (macOS) has no `\n` in replacements: use an editor or Python.
- The hand-labelling pages export a file to the browser's download folder (it once landed in
  another project's folder): copy it into `out/` before `import-labels` / `code-import`.
