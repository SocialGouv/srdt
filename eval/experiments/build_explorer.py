"""Build a single local HTML page to browse the dataset of the generic → KALI experiment:
select a question, then an IDCC (or the other way round), with counts, down to the KALI
links of that agreement contribution (a contribution without a link is listed too).

Read-only like the other scripts of this folder: reads Postgres, the KALI snapshot,
Elasticsearch (article titles) and the latest all-pairs run (ranks of the labelled
articles); writes eval/dataset-explorer.html only. The page embeds contribution links and
titles, so it stays local (this folder is untracked); run it from ingestion/:

    cd ingestion && SEARCH_HOSTNAME=http://localhost:9202 SEARCH_INDEX=chunks \
      SNAPSHOT_STORE=local .venv/bin/python ../eval/experiments/build_explorer.py
"""

import asyncio
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generic_to_kali import RUNS, Search, build_labels, norm_idcc, plain_text  # noqa: E402
from ingestion.config import load_config  # noqa: E402
from ingestion.pipeline import Inputs  # noqa: E402
from ingestion.settings import Settings, secret  # noqa: E402
from ingestion.snapshots.store import make_store  # noqa: E402
from ingestion.sources.postgres import load_documents  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "dataset-explorer.html"
RANK_CONFIGS = [
    "full knn", "full bm25", "full hybrid", "full rerank",
    "title knn", "title bm25", "title hybrid", "title rerank",
]


def latest_run() -> dict:
    runs = sorted(RUNS.glob("generic-to-kali-all-*"))
    if not runs:
        sys.exit("no all-pairs run found in eval/runs/")
    run = json.loads((runs[-1] / "results.json").read_text())
    run["dir"] = runs[-1].name
    return run


def agreement_names(settings: Settings) -> dict[str, dict[str, str]]:
    """IDCC (unpadded) -> short and full name, from the CDTN `conventions_collectives` documents."""

    async def fetch():
        pool = await asyncpg.create_pool(
            user=settings.postgres_user,
            password=secret(settings.postgres_password),
            database=settings.postgres_database_name,
            host=settings.postgres_database_url,
        )
        try:
            async with pool.acquire() as conn:
                return await conn.fetch(
                    """SELECT title, document->>'num' AS num, document->>'shortTitle' AS short
                       FROM public.documents
                       WHERE source = 'conventions_collectives' AND is_published = true AND is_available = true
                       ORDER BY slug"""
                )
        finally:
            await pool.close()

    names: dict[str, dict[str, str]] = {}
    for r in asyncio.run(fetch()):
        idcc = norm_idcc(r["num"])
        if idcc and idcc not in names:
            names[idcc] = {"short": (r["short"] or "").strip(), "title": (r["title"] or "").strip()}
    return names


def main() -> None:
    settings = Settings()
    inputs = Inputs(
        store=make_store(settings, "local"),
        config=load_config(Path("config/local.toml")),
        settings=settings,
    )
    docs = load_documents(settings, ["contributions", "contributions_idcc"])
    generics = {g.document["questionId"]: g for g in docs["contributions"]}
    run = latest_run()
    scored = {
        (r["question_id"], r["idcc"]): r for r in run["records"] if r["status"] == "ok"
    }
    search = Search(settings)

    rows: list[dict] = []
    wanted: dict[str, set[str]] = defaultdict(set)
    for a in docs["contributions_idcc"]:
        idcc = norm_idcc(a.idcc)
        qid = a.document.get("questionId")
        generic = generics.get(qid)
        record = scored.get((qid, idcc))
        if generic is None:
            scoring = "no generic answer"
        elif record is None:
            scoring = "no usable label"
        else:
            scoring = "scored"
        base = {
            "question": (generic.title if generic else a.title).strip(),
            "idcc": idcc,
            "generic": generic is not None,
            "scoring": scoring,
        }
        kept, dropped = build_labels(inputs, a)
        if not kept and not dropped:
            rows.append({**base, "status": "none"})
            continue
        for link in kept:
            wanted[idcc].add(link["chunk_id"])
            ranks = (record or {}).get("ranks", {})
            rows.append({
                **base,
                "status": "label",
                "label": link["label"],
                "num": link["num"],
                "kali_id": link["kali_id"],
                "chunk_id": link["chunk_id"],
                "url": link["canonical_url"],
                "ranks": {c: ranks.get(c, {}).get(link["chunk_id"]) for c in RANK_CONFIGS}
                if record else None,
            })
        for reason, link in dropped:
            rows.append({
                **base,
                "status": "dropped",
                "reason": reason,
                "label": link["label"],
                "num": link.get("num"),
                "kali_id": link["kali_id"],
                "url": link.get("canonical_url") or link["url"],
            })

    titles: dict[tuple[str, str], str] = {}
    for idcc, ids in wanted.items():
        ids_sorted = sorted(ids)
        for i in range(0, len(ids_sorted), 40):
            for article, title in search.article_titles(idcc, ids_sorted[i : i + 40]).items():
                titles[(idcc, article)] = title
    for row in rows:
        if row["status"] == "label":
            row["title"] = titles.get((row["idcc"], row["chunk_id"]), "")

    rows.sort(key=lambda r: (r["question"], int(r["idcc"] or 0), r.get("num") or ""))
    names = agreement_names(settings)
    used = {r["idcc"] for r in rows}
    missing = sorted(used - set(names), key=int)
    print(f"agreement names: {len(used) - len(missing)}/{len(used)}" + (f", missing {missing}" if missing else ""))
    data = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run": run["dir"],
        "index": run["provenance"]["index"],
        "kali_snapshot": run["provenance"]["kali_snapshot"],
        "rank_configs": RANK_CONFIGS,
        "agreements": {i: n for i, n in names.items() if i in used},
        "questions": {
            g.title.strip(): {"text": plain_text(g.document.get("content") or "")}
            for g in generics.values()
        },
        "rows": rows,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    OUT.write_text(TEMPLATE.replace("__DATA__", payload))
    n = {k: sum(r["status"] == k for r in rows) for k in ("label", "dropped", "none")}
    print(f"{len(rows)} rows ({n}) -> {OUT}")


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contributions and KALI links</title>
<style>
  :root { --bg:#fff; --fg:#1d2433; --muted:#5d6678; --line:#dfe3ea; --head:#f3f5f8; --accent:#1f5fbf;
          --sel:#e4edfb; --thumb:#c3c9d4; --thumb-hover:#9aa3b2; --ok:#1c7c3b; --warn:#a15c00; --off:#8a8f99; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#14171d; --fg:#e6e9ef; --muted:#9aa3b2; --line:#2a303b; --head:#1c212a; --accent:#7ab0ff;
            --sel:#22324d; --thumb:#3a4250; --thumb-hover:#566075; --ok:#59c47f; --warn:#e0a050; --off:#7b8190; } }
  * { box-sizing:border-box; }
  body { margin:0; padding:16px; background:var(--bg); color:var(--fg);
         font:14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  h1 { font-size:18px; margin:0 0 2px; }
  h2 { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:0 0 6px; font-weight:600; }
  .meta { color:var(--muted); font-size:12px; margin-bottom:10px; }
  .modes { display:inline-flex; border:1px solid var(--line); border-radius:6px; overflow:hidden; margin-bottom:12px; }
  .modes button { padding:6px 12px; border:0; background:var(--bg); color:var(--fg); font:inherit; cursor:pointer; }
  .modes button.on { background:var(--accent); color:#fff; }
  .grid { display:grid; grid-template-columns:minmax(220px,300px) minmax(220px,300px) 1fr; gap:12px; align-items:stretch;
          height:calc(100vh - 124px); min-height:420px; }
  @media (max-width:1000px) { .grid { grid-template-columns:1fr; height:auto; }
    ul.list { flex:none; max-height:40vh; } .scroll { overflow:visible; } }
  .col { min-width:0; min-height:0; display:flex; flex-direction:column; }
  .scroll { flex:1; min-height:0; overflow:auto; }
  input { width:100%; padding:6px 8px; margin-bottom:6px; border:1px solid var(--line); border-radius:6px;
          background:var(--bg); color:var(--fg); font:inherit; }
  ul.list { list-style:none; margin:0; padding:0; flex:1; min-height:0; overflow-y:auto; border:1px solid var(--line); border-radius:8px; }
  ul.list li { padding:7px 10px; border-bottom:1px solid var(--line); cursor:pointer; }
  ul.list li:last-child { border-bottom:0; }
  ul.list li:hover { background:var(--head); }
  ul.list li.sel { background:var(--sel); }
  .name { display:block; }
  ul.cards { padding:6px; background:var(--head); }
  ul.cards li { margin-bottom:6px; padding:9px 10px 8px; border:1px solid var(--line); border-radius:8px; background:var(--bg); }
  ul.cards li:last-child { margin-bottom:0; border-bottom:1px solid var(--line); }
  ul.cards li:hover { border-color:var(--accent); }
  ul.cards li.sel { background:var(--sel); border-color:var(--accent); box-shadow:inset 3px 0 0 var(--accent); }
  .card-name { display:flex; gap:6px; align-items:baseline; justify-content:space-between; font-weight:600; line-height:1.3; }
  .card-sub { font-size:12px; font-weight:400; color:var(--muted); line-height:1.3; margin-top:1px; }
  .pill { flex:none; font-size:11px; font-weight:500; padding:0 6px; border-radius:9px; border:1px solid var(--warn); color:var(--warn); }
  .tiles { display:grid; grid-template-columns:repeat(3, 1fr); gap:6px; margin-top:7px; }
  .tile b { display:block; font-size:16px; line-height:1.15; font-variant-numeric:tabular-nums; }
  .tile span { display:block; font-size:11px; color:var(--muted); }
  .cov { margin-top:7px; font-size:11px; color:var(--muted); }
  .cov .bar { height:5px; border-radius:3px; background:var(--line); overflow:hidden; margin-top:2px; }
  .cov .bar i { display:block; height:100%; background:var(--accent); }
  li.off .tile b, li.off .card-name { color:var(--muted); } li.off .cov .bar i { background:var(--off); }
  .badges { display:block; color:var(--muted); font-size:12px; }
  .empty { color:var(--muted); padding:10px; }
  ul.list, .scroll, pre, .wrap { scrollbar-width:thin; scrollbar-color:var(--thumb) transparent; }
  ul.list::-webkit-scrollbar, .scroll::-webkit-scrollbar, pre::-webkit-scrollbar, .wrap::-webkit-scrollbar { width:8px; height:8px; }
  ul.list::-webkit-scrollbar-track, .scroll::-webkit-scrollbar-track, pre::-webkit-scrollbar-track, .wrap::-webkit-scrollbar-track { background:transparent; }
  ul.list::-webkit-scrollbar-thumb, .scroll::-webkit-scrollbar-thumb, pre::-webkit-scrollbar-thumb, .wrap::-webkit-scrollbar-thumb {
    background:var(--thumb); border-radius:4px; border:2px solid transparent; background-clip:content-box; }
  ul.list::-webkit-scrollbar-thumb:hover, .scroll::-webkit-scrollbar-thumb:hover, pre::-webkit-scrollbar-thumb:hover, .wrap::-webkit-scrollbar-thumb:hover {
    background:var(--thumb-hover); border:2px solid transparent; background-clip:content-box; }
  .head { margin-bottom:8px; }
  .head b { font-size:15px; }
  .stats { color:var(--muted); font-size:13px; margin-top:2px; }
  details { margin:8px 0; } summary { cursor:pointer; color:var(--accent); }
  pre { white-space:pre-wrap; margin:6px 0 0; padding:8px 10px; border:1px solid var(--line); border-radius:6px;
        background:var(--head); font:inherit; max-height:260px; overflow:auto; }
  .wrap { overflow-x:auto; border:1px solid var(--line); border-radius:8px; }
  table { border-collapse:collapse; width:100%; min-width:640px; }
  th, td { padding:6px 10px; text-align:left; vertical-align:top; border-bottom:1px solid var(--line); }
  th { background:var(--head); white-space:nowrap; }
  tr:last-child td { border-bottom:0; }
  .nw { white-space:nowrap; }
  .tag { font-size:12px; white-space:nowrap; }
  .label { color:var(--ok); } .dropped { color:var(--warn); } .none { color:var(--off); }
  .sub { color:var(--muted); font-size:12px; }
  a { color:var(--accent); text-decoration:none; } a:hover { text-decoration:underline; }
  .note { color:var(--muted); font-size:12px; margin-top:10px; }
</style>
</head>
<body>
<h1>Contributions and KALI links</h1>
<div class="meta" id="meta"></div>
<div class="modes"><button id="modeQ">Question, then IDCC</button><button id="modeI">IDCC, then question</button></div>
<div class="grid">
  <section class="col"><h2 id="titleA"></h2><input id="fa" type="search"><ul class="list cards" id="listA"></ul></section>
  <section class="col"><h2 id="titleB"></h2><input id="fb" type="search"><ul class="list cards" id="listB"></ul></section>
  <section class="col">
    <h2>Links</h2>
    <div class="scroll">
    <div class="head" id="head"></div>
    <div id="gen"></div>
    <div class="wrap"><table>
      <thead><tr><th>Question</th><th>IDCC</th><th>Link label</th><th>Art.</th><th>Article in the index</th>
        <th>Status</th><th>Rank*</th><th>Légifrance</th></tr></thead>
      <tbody id="body"></tbody>
    </table></div>
    <p class="note">* Position of the article for the full-answer semantic search, among the articles of the agreement
    (first 64 chunks collapsed to articles). Hover for the seven other configurations. “–” = not in the list; blank = pair
    not scored. “Scored link” = a link resolving to an article with chunks in the index, in the same agreement. “top 5: 2/3”
    = labelled articles found in the first five. In the cards of the middle list, “2/3 top 5” and the bar give the labelled articles found in the first five. In the cards of the left list, “43 IDCC · 100 links · 11 dropped · 2.3 per IDCC” counts everything the editors linked: the IDCC (or questions) with a contribution, all their links, how many of those cannot be scored (dropped), and the average per IDCC. “93% of the 46 IDCC covered” is the share of the dataset’s agreements (or of its questions, in IDCC mode) that have a contribution.</p>
    </div>
  </section>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const data = JSON.parse(document.getElementById("data").textContent);
const rows = data.rows, meta = data.questions, R = "full knn";
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const plural = (n, w) => n + " " + w + (n === 1 ? "" : "s");
const agreement = i => (data.agreements || {})[i] || {short:"", title:""};
const idccLabel = i => "IDCC " + i + (agreement(i).short ? " · " + agreement(i).short : "");
const num = v => (v === null || v === undefined) ? "–" : v;

const pairs = new Map();
for (const r of rows) {
  const k = r.question + "||" + r.idcc;
  let p = pairs.get(k);
  if (!p) { p = {question:r.question, idcc:r.idcc, generic:r.generic, scoring:r.scoring, kept:[], dropped:[], rows:[]}; pairs.set(k, p); }
  p.rows.push(r);
  if (r.status === "label") p.kept.push(r); else if (r.status === "dropped") p.dropped.push(r);
}
const allPairs = [...pairs.values()];
const byQuestion = new Map(), byIdcc = new Map();
for (const p of allPairs) {
  if (!byQuestion.has(p.question)) byQuestion.set(p.question, []);
  byQuestion.get(p.question).push(p);
  if (!byIdcc.has(p.idcc)) byIdcc.set(p.idcc, []);
  byIdcc.get(p.idcc).push(p);
}
const universe = {q: byIdcc.size, i: byQuestion.size};
const links = ps => ps.reduce((n, p) => n + p.kept.length + p.dropped.length, 0);
const rankOf = r => r.ranks ? r.ranks[R] : undefined;
const found = (p, k) => p.kept.filter(r => rankOf(r) != null && rankOf(r) <= k).length;
const scoredPairs = ps => ps.filter(p => p.scoring === "scored");

let mode = "q", selA = null, selB = null, itemsA = [], itemsB = [];
const byFr = (a, b) => a.localeCompare(b, "fr");

$("meta").textContent = pairs.size + " agreement contributions · " + byQuestion.size + " questions · " + byIdcc.size +
  " IDCC · " + links(allPairs) + " KALI links · index " + data.index + " · KALI " + data.kali_snapshot +
  " · ranks from run " + data.run + " · built " + data.built_at;

function renderA() {
  const f = $("fa").value.trim().toLowerCase();
  const groups = mode === "q" ? byQuestion : byIdcc;
  let keys = [...groups.keys()];
  keys = mode === "q" ? keys.sort(byFr) : keys.sort((a, b) => a - b);
  if (f) keys = keys.filter(k => (mode === "q" ? k : idccLabel(k)).toLowerCase().includes(f));
  itemsA = keys;
  $("titleA").textContent = mode === "q" ? "Questions (" + groups.size + ")" : "IDCC (" + groups.size + ")";
  $("listA").innerHTML = keys.map((k, i) => {
    const ps = groups.get(k);
    const unit = mode === "q" ? "IDCC" : "question";
    // ground truth: every link the editors put in these contributions, whether or not it can be scored
    const n = links(ps), dropped = ps.reduce((m, p) => m + p.dropped.length, 0);
    // covered = IDCC (or questions) with a contribution, out of all those of the dataset
    const covered = new Set(ps.map(p => mode === "q" ? p.idcc : p.question)).size;
    const total = universe[mode];
    const pct = total ? Math.round(100 * covered / total) : 0;
    const tile = (v, l) => '<div class="tile"><b>' + v + "</b><span>" + l + "</span></div>";
    const word = unit + (unit === "question" && ps.length !== 1 ? "s" : "");
    return '<li data-i="' + i + '" class="' + (k === selA ? "sel" : "") + '">' +
      '<div class="card-name"><span>' + esc(mode === "q" ? k : "IDCC " + k) + "</span></div>" +
      (mode === "q" ? "" : '<div class="card-sub">' + esc(agreement(k).short) + "</div>") +
      '<div class="tiles">' + tile(ps.length, word) +
      tile(n, (n === 1 ? "link" : "links") + (dropped ? " · " + dropped + " dropped" : "")) +
      tile((n / ps.length).toFixed(1), "per " + unit) + "</div>" +
      '<div class="cov">' + pct + "% of the " + total + " " + (mode === "q" ? "IDCC" : "questions") + " covered" +
      '<div class="bar"><i style="width:' + pct + '%"></i></div></div></li>';
  }).join("") || '<li class="empty">No match</li>';
}
function pairsOfA() { return selA === null ? [] : (mode === "q" ? byQuestion : byIdcc).get(selA) || []; }
function renderB() {
  const all = pairsOfA().slice().sort(mode === "q" ? (a, b) => a.idcc - b.idcc : (a, b) => byFr(a.question, b.question));
  const f = $("fb").value.trim().toLowerCase();
  const ps = f ? all.filter(p => (mode === "q" ? idccLabel(p.idcc) : p.question).toLowerCase().includes(f)) : all;
  itemsB = ps;
  const count = (f ? ps.length + " of " : "") + all.length;
  $("titleB").textContent = selA === null ? "" : (mode === "q" ? "IDCC (" + count + ")" : "Questions (" + count + ")");
  $("listB").innerHTML = ps.map((p, i) => {
    const kept = p.kept.length, scored = p.scoring === "scored";
    const tile = (v, l) => '<div class="tile"><b>' + v + "</b><span>" + l + "</span></div>";
    const f5 = found(p, 5), pct = kept ? Math.round(100 * f5 / kept) : 0;
    const pill = scored ? "" : p.scoring === "no generic answer" ? "no generic answer" : "not scored";
    let foot = "";
    if (scored) foot = '<div class="cov">' + f5 + " of " + plural(kept, "link") + " found in the top 5 (" + pct + "%)" +
      '<div class="bar"><i style="width:' + pct + '%"></i></div></div>';
    else if (!kept && !p.dropped.length) foot = '<div class="cov">no KALI link</div>';
    return '<li data-i="' + i + '" class="' + (selB === p ? "sel " : "") + (scored ? "" : "off") + '">' +
      '<div class="card-name"><span>' + esc(mode === "q" ? "IDCC " + p.idcc : p.question) + "</span>" +
      (pill ? '<span class="pill">' + pill + "</span>" : "") + "</div>" +
      (mode === "q" ? '<div class="card-sub">' + esc(agreement(p.idcc).short) + "</div>" : "") +
      '<div class="tiles">' + tile(kept, kept === 1 ? "link" : "links") + tile(p.dropped.length, "dropped") +
      tile(scored ? f5 + "/" + kept : "–", "top 5") + "</div>" + foot + "</li>";
  }).join("");
}
function rankCell(r) {
  if (!r.ranks) return "";
  const tip = data.rank_configs.map(c => c + ": " + num(r.ranks[c])).join("\\n");
  return '<span title="' + esc(tip) + '">' + num(r.ranks[R]) + "</span>";
}
function statusCell(r) {
  if (r.status === "label") return '<span class="tag label">scored link</span>';
  if (r.status === "dropped") return '<span class="tag dropped">dropped</span><div class="sub">' + esc(r.reason) + "</div>";
  return '<span class="tag none">no KALI link</span>';
}
function renderC() {
  const ps = selB ? [selB] : pairsOfA();
  const question = mode === "q" ? selA : (selB ? selB.question : null);
  let title = "";
  if (selB) title = selB.question + " · " + idccLabel(selB.idcc);
  else if (selA !== null) title = mode === "q" ? selA : idccLabel(selA);
  const sp = scoredPairs(ps), kept = sp.reduce((n, p) => n + p.kept.length, 0);
  const dropped = ps.reduce((n, p) => n + p.dropped.length, 0);
  const none = ps.filter(p => !p.kept.length && !p.dropped.length).length;
  // same base as the cards: the scored pairs, or all of them when none is scored
  const unit = selB ? "contribution" : mode === "q" ? "IDCC" : "question", base = sp.length ? sp : ps;
  const keptBase = base.reduce((n, p) => n + p.kept.length, 0);
  let stats = (sp.length ? "" : "not scored · ") + (selB ? "" : sp.length ? sp.length + " of " + ps.length + " " : ps.length + " ") +
    (selB ? "1 contribution" : unit + (unit === "question" && ps.length !== 1 ? "s" : "") + (sp.length ? " scored" : "")) +
    " · " + plural(keptBase, "link") + " · " + dropped + " dropped · " + none + " without a link";
  if (sp.length) stats += " · found in the first 5 / 10: " + sp.reduce((n, p) => n + found(p, 5), 0) + " / " +
    sp.reduce((n, p) => n + found(p, 10), 0) + " of " + kept;
  const idccFull = mode === "q" ? (selB ? selB.idcc : null) : selA;
  const full = idccFull !== null ? agreement(idccFull).title : "";
  $("head").innerHTML = title ? "<b>" + esc(title) + "</b>" + (full ? '<div class="sub">' + esc(full) + "</div>" : "") +
    '<div class="stats">' + esc(stats) + "</div>" : "";
  const text = question && meta[question] ? meta[question].text : "";
  $("gen").innerHTML = text ? "<details><summary>Generic answer</summary><pre>" + esc(text) + "</pre></details>" : "";
  const list = ps.flatMap(p => p.rows);
  $("body").innerHTML = list.map(r =>
    "<tr><td>" + esc(r.question) + "</td>" +
    '<td class="nw" title="' + esc(agreement(r.idcc).title) + '">' + esc(r.idcc) + "</td>" +
    "<td>" + esc(r.label || "") + (r.kali_id ? '<div class="sub">' + esc(r.kali_id) + "</div>" : "") + "</td>" +
    '<td class="nw">' + esc(r.num || "") + "</td>" +
    "<td>" + esc(r.title || "") + "</td><td>" + statusCell(r) + "</td>" +
    '<td class="nw">' + rankCell(r) + "</td>" +
    "<td>" + (r.url ? '<a href="' + esc(r.url) + '" target="_blank" rel="noopener">open</a>' : "") + "</td></tr>").join("");
}
function render() { renderA(); renderB(); renderC(); }
function setMode(m) {
  mode = m; selB = null; $("fa").value = ""; $("fa").placeholder = m === "q" ? "Filter questions…" : "Filter IDCC or name…";
  $("fb").value = ""; $("fb").placeholder = m === "q" ? "Filter IDCC or name…" : "Filter questions…";
  $("modeQ").className = m === "q" ? "on" : ""; $("modeI").className = m === "i" ? "on" : "";
  renderA(); selA = itemsA.length ? itemsA[0] : null; render();
}
$("modeQ").addEventListener("click", () => setMode("q"));
$("modeI").addEventListener("click", () => setMode("i"));
$("fa").addEventListener("input", renderA);
$("fb").addEventListener("input", renderB);
$("listA").addEventListener("click", e => {
  const li = e.target.closest("li[data-i]"); if (!li) return;
  selA = itemsA[Number(li.dataset.i)]; selB = null; $("fb").value = ""; render();
});
$("listB").addEventListener("click", e => {
  const li = e.target.closest("li[data-i]"); if (!li) return;
  const p = itemsB[Number(li.dataset.i)]; selB = selB === p ? null : p; render();
});
setMode("q");
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
