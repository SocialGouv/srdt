import json
import logging
import os
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer

from acco_analysis import (
    accords_site,
    coding,
    coding_labelling,
    crypto_site,
    flavours,
    flavours_report,
    io,
    labelling,
    metrics,
    note_rapprochement,
    report_facts,
    report_pdf,
    report_polish,
    rollup,
    site,
)
from acco_analysis import cluster as clustering
from acco_analysis import report as reporting
from acco_analysis.albert import Albert
from acco_analysis.corpus import load_agreements
from acco_analysis.extract import extract_passages, find_anchors
from acco_analysis.label import label_cluster, pick
from acco_analysis.merge import merge_clusters
from acco_analysis.metrics_report import csv_tables
from acco_analysis.metrics_report import to_markdown as metrics_markdown
from acco_analysis.relevance import KEPT, LABELS, classify
from acco_analysis.settings import load_settings

app = typer.Typer(no_args_is_help=True, help="Heat clauses of the ACCO agreements.")
logger = logging.getLogger(__name__)


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


@app.command()
def extract():
    """Stage 1: the passages that match a heat term -> out/passages.jsonl."""
    snapshot_id, agreements = load_agreements(load_settings().snapshot_dir)
    passages = [p for a in agreements for p in extract_passages(a)]
    n = io.write_jsonl(io.path("passages.jsonl"), (p.to_json() for p in passages))
    with_passage = {p.agreement_id for p in passages}
    typer.echo(
        json.dumps(
            {
                "snapshot": snapshot_id,
                "agreements": len(agreements),
                "agreements_with_a_passage": len(with_passage),
                "passages": n,
                "windowed": sum(p.windowed for p in passages),
                "anchor_in_heading": sum(p.in_heading for p in passages),
                "with_a_collection_phrase": sum(
                    any(a.kind == "phrase" for a in p.anchors) for p in passages
                ),
                "variant_only": sum(
                    all(a.kind == "variant" for a in p.anchors) for p in passages
                ),
                "anchor_terms": Counter(
                    a.term for p in passages for a in p.anchors
                ).most_common(12),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command()
def filter(
    check_model: Annotated[
        str | None,
        typer.Option(help="Second model: its disagreements are where to look first"),
    ] = "gemma-4-31b-it",
):
    """Stage 2: label passages specific, generic or mention -> out/relevance.jsonl."""
    from dataclasses import replace

    settings = load_settings()
    passages = list(io.read_jsonl(io.path("passages.jsonl")))
    main = classify(Albert(settings), passages)
    checked = (
        classify(Albert(replace(settings, llm_model=check_model)), passages)
        if check_model
        else {}
    )
    rows = []
    for p in passages:
        row = {"id": p["id"], "model": settings.llm_model, **main[p["id"]]}
        if checked:
            row |= {
                "check_model": check_model,
                "check_label": checked[p["id"]]["label"],
                "agree": checked[p["id"]]["label"] == main[p["id"]]["label"],
            }
        rows.append(row)
    io.write_jsonl(io.path("relevance.jsonl"), rows)
    summary: dict = {"passages": len(rows), "labels": Counter(r["label"] for r in rows)}
    if checked:
        summary["agreement"] = round(sum(r["agree"] for r in rows) / len(rows), 3)
        summary["kept_by_both"] = sum(
            r["label"] in KEPT and r["check_label"] in KEPT for r in rows
        )
        summary["kept_by_one"] = sum(
            (r["label"] in KEPT) != (r["check_label"] in KEPT) for r in rows
        )
    summary["agreements_with_a_kept_passage"] = len(
        {
            p["agreement_id"]
            for p, r in zip(passages, rows, strict=True)
            if r["label"] in KEPT
        }
    )
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))


@app.command()
def sample(size: int = 100):
    """Passages to label by hand -> out/label_sample.csv (fill in human_label)."""
    passages = list(io.read_jsonl(io.path("passages.jsonl")))
    relevance = {r["id"]: r for r in io.read_jsonl(io.path("relevance.jsonl"))}
    rows = labelling.make_sample(passages, relevance, size)
    labelling.write_csv(io.path("label_sample.csv"), rows)
    typer.echo(
        f"{len(rows)} rows in out/label_sample.csv: fill human_label with "
        f"{', '.join(LABELS)}, then run `acco-analysis evaluate`"
    )


@app.command()
def queue():
    """Order out/label_sample.csv for labelling and write out/label_queue.json.

    The queue ({"items": [...]}) is what the labelling page shows: id, order, heading,
    excerpt, the heat
    terms to highlight and the Légifrance link. It holds no model label, so the
    labelling is blind."""
    file = io.path("label_sample.csv")
    rows = labelling.read_csv(file)
    passages = {p["id"]: p for p in io.read_jsonl(io.path("passages.jsonl"))}
    rows = labelling.queue_order(
        [
            {
                **{c: "" for c in labelling.COLUMNS},
                **r,
                "list_like": "1"
                if labelling.looks_like_list(passages[r["id"]]["text"])
                else "0",
            }
            for r in rows
        ]
    )
    labelling.write_csv(file, rows)
    items = []
    for r in rows:
        text = unicodedata.normalize("NFC", r["excerpt"])
        items.append(
            {
                "id": r["id"],
                "order": int(r["order"]),
                "heading": unicodedata.normalize("NFC", r["heading"]),
                "excerpt": text,
                "terms": sorted({a.term for a in find_anchors(text)}),
                "url": r["url"],
            }
        )
    # one document for the page (`queue/main`): ArtifactData sets it from this file
    io.path("label_queue.json").write_text(
        json.dumps({"items": items}, ensure_ascii=False)
    )
    first = rows[:40]
    typer.echo(
        json.dumps(
            {
                "rows": len(rows),
                "list_like": sum(r["list_like"] == "1" for r in rows),
                "first_40": {
                    "labels": dict(Counter(r["llm_label"] for r in first)),
                    "disagreements": sum(
                        r["llm_label"] != r["check_label"] for r in first
                    ),
                    "list_like": sum(r["list_like"] == "1" for r in first),
                },
            }
        )
    )


@app.command("import-labels")
def import_labels(file: Path):
    """Fill out/label_sample.csv from the labels read back from the page.

    `file` is a JSON list of {"id", "label", "note"}; label is specific, generic,
    mention or unsure."""
    labels = json.loads(file.read_text())
    sample = io.path("label_sample.csv")
    rows = labelling.import_labels(labelling.read_csv(sample), labels)
    labelling.write_csv(sample, rows)
    typer.echo(
        json.dumps(
            Counter(r["human_label"] or "(not labelled)" for r in rows),
            ensure_ascii=False,
        )
    )


@app.command()
def evaluate():
    """Score the filter against out/label_sample.csv."""
    rows = labelling.read_csv(io.path("label_sample.csv"))
    typer.echo(json.dumps(labelling.evaluate(rows), ensure_ascii=False, indent=2))


def _kept() -> tuple[list[dict], dict[str, dict]]:
    """The passages labelled specific or generic, and every label."""
    relevance = {r["id"]: r for r in io.read_jsonl(io.path("relevance.jsonl"))}
    passages = [
        p
        for p in io.read_jsonl(io.path("passages.jsonl"))
        if relevance[p["id"]]["label"] in KEPT
    ]
    return passages, relevance


@app.command()
def cluster(
    method: Annotated[str, typer.Option(help="kmeans or hdbscan")] = "kmeans",
    k: Annotated[int, typer.Option(help="kmeans: number of groups")] = 15,
    min_cluster_size: Annotated[int, typer.Option(help="hdbscan")] = 15,
    selection: Annotated[str, typer.Option(help="hdbscan: leaf or eom")] = "leaf",
):
    """Stage 3: embed and cluster the kept passages -> out/clusters.json."""
    import numpy as np

    passages, _ = _kept()
    vectors = Albert(load_settings()).embed(
        [clustering.passage_text(p) for p in passages]
    )
    params = clustering.Params(
        method=method, k=k, min_cluster_size=min_cluster_size, selection=selection
    )
    labels = clustering.cluster(vectors, params)
    scores = clustering.stability(vectors, labels, params)
    np.save(io.path("embeddings.npy"), vectors)
    io.path("clusters.json").write_text(
        json.dumps(
            {
                "params": params.__dict__,
                "stability": {
                    "scores": scores,
                    "mean": round(sum(scores) / len(scores), 3),
                    "min": round(min(scores), 3),
                },
                "assignments": {
                    p["id"]: int(c) for p, c in zip(passages, labels, strict=True)
                },
            },
            ensure_ascii=False,
        )
    )
    sizes = Counter(int(c) for c in labels)
    typer.echo(
        json.dumps(
            {
                "passages": len(passages),
                "clusters": len([c for c in sizes if c >= 0]),
                "noise": sizes.get(-1, 0),
                "sizes": [n for c, n in sizes.most_common() if c >= 0],
                "stability_mean": round(sum(scores) / len(scores), 3),
                "stability_min": round(min(scores), 3),
            }
        )
    )


@app.command()
def label():
    """Stage 4: name and describe each cluster (LLM) -> out/labels.json."""
    import numpy as np

    passages, _ = _kept()
    assignments = json.loads(io.path("clusters.json").read_text())["assignments"]
    vectors = np.load(io.path("embeddings.npy"))
    clusters = np.array([assignments[p["id"]] for p in passages])
    albert = Albert(load_settings())
    labels = {}
    for cluster_id in sorted(set(clusters.tolist()) - {-1}):
        members = np.flatnonzero(clusters == cluster_id)
        labels[cluster_id] = label_cluster(albert, passages, pick(vectors, members))
        logger.info(f"cluster {cluster_id}: {labels[cluster_id]['label']}")
    io.path("labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1))
    typer.echo(
        f"{len(labels)} clusters labelled, "
        f"{sum(v['quotes_dropped'] for v in labels.values())} quotes dropped "
        "as not verbatim"
    )


@app.command()
def merge():
    """Stage 4b: group the labelled clusters into families -> out/families.json.

    Reads out/clauses.json (run `report` first); run `report` again to add them."""
    clusters = json.loads(io.path("clauses.json").read_text())["clusters"]
    result = merge_clusters(Albert(load_settings()), clusters)
    io.path("families.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1)
    )
    by_id = {c["cluster"]: c for c in clusters}
    for family in result["families"]:
        size = sum(by_id[i]["passages"] for i in family["clusters"])
        typer.echo(
            f"{family['label']} ({size} passages): "
            f"{', '.join(str(i + 1) for i in family['clusters'])}"
        )
    if result["retried"] or result["unresolved"]:
        typer.echo(
            f"retried: {result['retried']}, unresolved: {result['unresolved']}",
            err=True,
        )


@app.command()
def open_code(
    per_family: Annotated[int, typer.Option(help="passages per family")] = 30,
):
    """Codebook step 1: free description of a sample, drawn by family
    -> out/open_coding.jsonl and out/open_coding.md (read it to write the codebook)."""
    passages, _ = _kept()
    assignments = json.loads(io.path("clusters.json").read_text())["assignments"]
    families = json.loads(io.path("families.json").read_text())
    sample = coding.sample_by_family(passages, assignments, families, per_family)
    chosen = [p for family in sorted(sample) for p in sample[family]]
    coded = coding.open_code(Albert(load_settings()), chosen)
    rows = [
        {
            "family": n,
            "family_label": families["families"][n]["label"],
            "cluster": assignments[p["id"]],
            "heading": p["heading"],
            "text": p["text"],
            **coded[p["id"]],
        }
        for n, passages_of in sorted(sample.items())
        for p in passages_of
    ]
    io.write_jsonl(io.path("open_coding.jsonl"), rows)
    io.path("open_coding.md").write_text(coding.open_coding_markdown(rows))
    typer.echo(
        json.dumps(
            {
                "coded": len(rows),
                "by_family": Counter(r["family_label"] for r in rows),
                "not_about_heat": sum(r.get("about_heat") is False for r in rows),
                "quotes_dropped": sum(not r.get("quote") for r in rows),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command()
def code(
    pilot: Annotated[
        int, typer.Option(help="code this many passages (spread over the old families)")
    ] = 0,
    check_model: Annotated[
        str | None, typer.Option(help="second model, for the agreement figures")
    ] = "gemma-4-31b-it",
):
    """Closed coding with the codebook -> out/coding.jsonl (out/coding_pilot.jsonl)."""
    from dataclasses import replace

    settings = load_settings()
    passages, _ = _kept()
    if pilot:
        assignments = json.loads(io.path("clusters.json").read_text())["assignments"]
        families = json.loads(io.path("families.json").read_text())
        seen = {r["id"] for r in io.read_jsonl(io.path("open_coding.jsonl"))}
        sample = coding.sample_by_family(
            [p for p in passages if p["id"] not in seen],
            assignments,
            families,
            pilot // len(families["families"]),
            seed=1,
        )
        passages = [p for family in sorted(sample) for p in sample[family]]
    main = coding.code_passages(Albert(settings), passages)
    checked = (
        coding.code_passages(Albert(replace(settings, llm_model=check_model)), passages)
        if check_model
        else {}
    )
    dropped = [
        p["id"]
        for p in passages
        if p["id"] not in main or (checked and p["id"] not in checked)
    ]
    if dropped:
        typer.echo(f"not coded by both models, left out: {dropped}")
    rows = [
        {
            "id": p["id"],
            "agreement_id": p["agreement_id"],
            "main": main[p["id"]],
            "check": checked.get(p["id"]),
        }
        for p in passages
        if p["id"] not in dropped
    ]
    name = "coding_pilot.jsonl" if pilot else "coding.jsonl"
    io.write_jsonl(io.path(name), rows)
    summary = coding.summarise(main)
    if checked:
        summary["reliability"] = coding.reliability(main, checked)
        summary["check_model_summary"] = coding.summarise(checked)
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=1))


@app.command()
def code_queue(size: int = 40):
    """Hand check, step 1: out/coding_check.html, the page to code `size` pilot
    passages blind (open it in a browser, export the answers when done)."""
    rows = list(io.read_jsonl(io.path("coding_pilot.jsonl")))
    passages = {p["id"]: p for p in io.read_jsonl(io.path("passages.jsonl"))}
    assignments = json.loads(io.path("clusters.json").read_text())["assignments"]
    family_of = coding.family_of_clusters(
        json.loads(io.path("families.json").read_text())
    )
    groups = {r["id"]: family_of[assignments[r["id"]]] for r in rows}
    items = coding_labelling.queue_items(rows, passages, groups, size)
    io.path("coding_check.html").write_text(coding_labelling.render_page(items))
    typer.echo(f"{len(items)} passages in out/coding_check.html")


@app.command()
def code_import(file: Path):
    """Hand check, step 2: the page's exported answers -> out/coding_labels.json."""
    labels = coding_labelling.read_labels(file)
    io.path("coding_labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=1)
    )
    typer.echo(f"{len(labels)} validated passages in out/coding_labels.json")


@app.command()
def code_evaluate():
    """Hand check, step 3: score the two models against the hand coding."""
    rows = list(io.read_jsonl(io.path("coding_pilot.jsonl")))
    labels = json.loads(io.path("coding_labels.json").read_text())
    typer.echo(
        json.dumps(
            coding_labelling.evaluate(rows, labels), ensure_ascii=False, indent=1
        )
    )


@app.command()
def report():
    """Stage 5: out/clauses.json and out/clauses.md (with families.json if present)."""
    settings = load_settings()
    snapshot_id, agreements = load_agreements(settings.snapshot_dir)
    passages = list(io.read_jsonl(io.path("passages.jsonl")))
    relevance = {r["id"]: r for r in io.read_jsonl(io.path("relevance.jsonl"))}
    clusters = json.loads(io.path("clusters.json").read_text())
    labels = {
        int(k): v for k, v in json.loads(io.path("labels.json").read_text()).items()
    }
    first = next(iter(relevance.values()))
    families_file = io.path("families.json")
    families = json.loads(families_file.read_text()) if families_file.exists() else None
    result = reporting.build(
        families=families,
        snapshot_id=snapshot_id,
        agreements=agreements,
        passages=passages,
        relevance=relevance,
        assignments=clusters["assignments"],
        labels=labels,
        meta={
            "stability": clusters["stability"],
            "clustering": clusters["params"],
            "models": f"labels {first['model']}, check {first.get('check_model')}, "
            f"embeddings {settings.embedding_model}",
        },
    )
    io.path("clauses.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    io.path("clauses.md").write_text(reporting.to_markdown(result))
    typer.echo("wrote out/clauses.json and out/clauses.md")


@app.command(name="rollup")
def rollup_command():
    """Stage 6: one profile per agreement (strict: both models, loose: either) and the
    clauses shared between agreements -> out/profiles.jsonl, out/templates.json."""
    import numpy as np

    passages, _ = _kept()
    vectors = np.load(io.path("embeddings.npy"))
    template_of = rollup.template_groups(
        [p["id"] for p in passages],
        [p["agreement_id"] for p in passages],
        [p["text"] for p in passages],
        vectors,
    )
    rows = list(io.read_jsonl(io.path("coding.jsonl")))
    profiles = {
        m: rollup.agreement_profiles(rows, m, template_of) for m in rollup.MODES
    }
    io.write_jsonl(
        io.path("profiles.jsonl"),
        (p for m in rollup.MODES for p in profiles[m].values()),
    )
    io.path("templates.json").write_text(
        json.dumps(template_of, ensure_ascii=False, indent=0)
    )
    groups = Counter(template_of.values())
    typer.echo(
        json.dumps(
            {
                "agreements_with_a_heat_clause": {
                    m: len(p) for m, p in profiles.items()
                },
                "template_groups": len(groups),
                "passages_in_a_template": len(template_of),
                "largest_group_passages": max(groups.values(), default=0),
            },
            indent=1,
        )
    )


@app.command(name="metrics")
def metrics_command():
    """Stage 7: counts, shares and breakdowns -> out/metrics.json, out/metrics.md and
    the flat tables out/metrics_*.csv."""
    import csv

    snapshot_id, agreements = load_agreements(load_settings().snapshot_dir)
    rows = list(io.read_jsonl(io.path("coding.jsonl")))
    profiles: dict[str, dict[str, dict]] = {m: {} for m in rollup.MODES}
    for p in io.read_jsonl(io.path("profiles.jsonl")):
        profiles[p["mode"]][p["agreement_id"]] = p
    template_of = json.loads(io.path("templates.json").read_text())
    clusters = json.loads(io.path("clusters.json").read_text())["assignments"]
    relevance = Counter(r["label"] for r in io.read_jsonl(io.path("relevance.jsonl")))
    result = metrics.build(
        snapshot_id=snapshot_id,
        agreements=agreements,
        rows=rows,
        profiles=profiles,
        template_of=template_of,
        clusters=clusters,
        relevance=dict(relevance),
    )
    io.path("metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    io.path("metrics.md").write_text(metrics_markdown(result))
    for name, table in csv_tables(result).items():
        fields = list(dict.fromkeys(k for row in table for k in row))
        with open(io.path(name), "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(table)
    n_tables = len(csv_tables(result))
    typer.echo(f"wrote out/metrics.json, out/metrics.md and {n_tables} CSV files")
    typer.echo(
        "problems: "
        + (json.dumps(result["problems"]) if result["problems"] else "none")
    )


@app.command(name="flavours")
def flavours_command(
    describe: Annotated[
        bool, typer.Option(help="ask the model to name and describe each flavour")
    ] = True,
):
    """Stage 8: the recurring combinations of codes inside each family, counted, then
    described (LLM, checked quotes) -> out/flavours.json."""
    import csv

    import numpy as np

    snapshot_id, agreements = load_agreements(load_settings().snapshot_dir)
    passages, _ = _kept()
    rows = list(io.read_jsonl(io.path("coding.jsonl")))
    profiles: dict[str, dict[str, dict]] = {m: {} for m in rollup.MODES}
    for p in io.read_jsonl(io.path("profiles.jsonl")):
        profiles[p["mode"]][p["agreement_id"]] = p
    result = flavours.build(
        albert=Albert(load_settings()) if describe else None,
        agreements=agreements,
        rows=rows,
        profiles=profiles,
        passages=passages,
        vectors=np.load(io.path("embeddings.npy")),
        template_of=json.loads(io.path("templates.json").read_text()),
    )
    result["snapshot"] = snapshot_id
    io.path("flavours.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1)
    )
    io.path("flavours.md").write_text(flavours_report.to_markdown(result))
    csv_file = io.path("flavours.csv")
    table = flavours_report.csv_rows(result)
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    for name, family in result["families"].items():
        n_flavours = len(family["flavours"])
        typer.echo(
            f"{name}: {family['strict']} agreements, {n_flavours} flavours, "
            f"other {family['other']['strict']}"
        )


def _profiles() -> dict[str, dict[str, dict]]:
    profiles: dict[str, dict[str, dict]] = {m: {} for m in rollup.MODES}
    for p in io.read_jsonl(io.path("profiles.jsonl")):
        profiles[p["mode"]][p["agreement_id"]] = p
    return profiles


def _report_inputs() -> tuple[dict, dict, dict, dict]:
    """(metrics, facts, passages by id, agreements by id) the report is built from."""
    _, agreements = load_agreements(load_settings().snapshot_dir)
    passages, relevance = _kept()
    by_id = {p["id"]: p for p in passages}
    coding = list(io.read_jsonl(io.path("coding.jsonl")))
    return (
        json.loads(io.path("metrics.json").read_text()),
        report_facts.compute(
            coding,
            by_id,
            relevance,
            {a.id: a for a in agreements},
            _profiles(),
        ),
        by_id,
        {a.id: a for a in agreements},
    )


def _quotes() -> dict[str, tuple[str, str]]:
    return report_pdf.load_quotes(io.path(report_pdf.QUOTES_FILE))


def _report_data() -> dict:
    """The figures and checked quotes of the report (see `report_pdf.build_data`), with
    the links to the published UI when `ACCO_SITE_URL` and `out/site-enc/` allow it."""
    metrics, facts, by_id, agreements = _report_inputs()
    ui = report_pdf.ui_links(io.path("site-enc"), load_settings().site_url)
    quotes = report_pdf.resolve_quotes(by_id, agreements, _quotes(), ui=ui)
    if ui is None:
        typer.echo("no links to the UI: set ACCO_SITE_URL and build out/site-enc/")
    elif no_page := [k for k, q in quotes.items() if q["ui"] is None]:
        typer.echo(f"no UI page for: {', '.join(no_page)}")
    return report_pdf.build_data(
        metrics, facts, quotes, ui_home=ui.home if ui else None
    )


def _web_report(salt: bytes, pages: frozenset[str]) -> str:
    """The report as a page of the site being built: its links to agreement pages are
    relative and use the salt of that build."""
    metrics, facts, by_id, agreements = _report_inputs()
    ui = report_pdf.UiLinks("", salt, pages)
    data = report_pdf.build_data(
        metrics,
        facts,
        report_pdf.resolve_quotes(by_id, agreements, _quotes(), ui=ui),
    )
    return report_pdf.render_html(data, io.path("report-web"))


@app.command(name="report-pdf")
def report_pdf_command():
    """Stage 12: out/report.pdf, the French analysis note (needs typst)."""
    pdf = io.path("report.pdf")
    pages = report_pdf.render(_report_data(), io.path("report"), pdf)
    typer.echo(f"out/report.pdf ({pages} pages, {pdf.stat().st_size // 1024} KB)")


@app.command(name="report-polish")
def report_polish_command():
    """Stage 12b: an LLM improves the report's French -> out/report-polished.pdf.

    Figures and quotes must come back untouched (checked, retried when rejected).
    `report.typ` is never overwritten: compare, then copy the new one if it is better.
    """
    data = _report_data()
    source, notes = report_polish.polish(
        Albert(load_settings()),
        report_pdf.TEMPLATE.read_text(),
        data["f"],
        data["quotes"],
    )
    polished = io.path("report-polished.typ")
    polished.write_text(source)
    notes_file = io.path("report-polished-notes.md")
    notes_file.write_text(notes + "\n")
    pdf = io.path("report-polished.pdf")
    pages = report_pdf.render(data, io.path("report-polished"), pdf, template=polished)
    typer.echo(f"out/report-polished.pdf ({pages} pages)")
    typer.echo("out/report-polished.typ         (the polished template)")
    typer.echo("out/report-polished-notes.md    (the model's doubts: read them)")


@app.command(name="note-rapprochement")
def note_rapprochement_command(
    polish: Annotated[
        bool, typer.Option(help="Have the model polish the French (checked)")
    ] = True,
):
    """Stage 12c: out/note-rapprochement.pdf, a note that sets this analysis beside the
    DS2/DS1 note on climate adaptation (needs typst; the polish calls Albert)."""
    metrics, facts, _, _ = _report_inputs()
    report_f = report_pdf.build_data(metrics, facts, {})["f"]
    data = note_rapprochement.build_data(report_f, facts, metrics["snapshot"])
    source = note_rapprochement.TEMPLATE.read_text()
    if polish:
        source, notes = report_polish.polish(
            Albert(load_settings()),
            source,
            data["f"],
            {},
            system=note_rapprochement.SYSTEM,
            meanings=note_rapprochement.MEANINGS,
            start=note_rapprochement.START,
        )
        io.path("note-rapprochement-notes.md").write_text(notes + "\n")
        typer.echo("out/note-rapprochement-notes.md  (the model's doubts: read them)")
    typst_file = io.path("note-rapprochement.typ")
    typst_file.write_text(source)
    pdf = io.path("note-rapprochement.pdf")
    pages = report_pdf.render(
        data, io.path("note-rapprochement"), pdf, template=typst_file
    )
    typer.echo(f"out/note-rapprochement.pdf ({pages} pages)")


@app.command(name="site")
def site_command():
    """Stage 9: out/flavours.html, a local page to browse the flavours (no network)."""
    _, agreements = load_agreements(load_settings().snapshot_dir)
    data = site.build_data(
        json.loads(io.path("flavours.json").read_text()),
        json.loads(io.path("metrics.json").read_text()),
        agreements,
        _profiles(),
    )
    io.path("flavours.html").write_text(site.render(data))
    typer.echo(
        f"out/flavours.html ({io.path('flavours.html').stat().st_size // 1024} KB)"
    )


@app.command()
def accords(
    encrypt: Annotated[
        bool,
        typer.Option(
            help="Write out/site-enc/, encrypted with a password, instead of out/site/"
        ),
    ] = False,
    report: Annotated[
        bool, typer.Option(help="Add the analysis note as a page (needs typst)")
    ] = True,
):
    """Stage 10: the nuances page with a page per agreement (no model).

    Plain: out/site/, to preview with `python -m http.server -d out/site`. Encrypted:
    out/site-enc/, with the password of ACCO_SITE_PASSWORD (asked for when unset)."""
    if report:
        report_pdf.typst_binary()  # fail now, not after the password and the build
    password = None
    if encrypt:
        password = os.environ.get("ACCO_SITE_PASSWORD") or typer.prompt(
            "Password", hide_input=True, confirmation_prompt=True
        )
        if crypto_site.weak_password(password):
            typer.echo(
                f"Warning: under {crypto_site.MIN_PASSWORD} characters. The encrypted "
                "files are public: use a long random passphrase.",
                err=True,
            )
    snapshot_id, agreements = load_agreements(load_settings().snapshot_dir)
    out_dir = io.path("site-enc" if encrypt else "site")
    summary = accords_site.build_site(
        out_dir,
        password=password,
        flavours=json.loads(io.path("flavours.json").read_text()),
        metrics=json.loads(io.path("metrics.json").read_text()),
        agreements=agreements,
        profiles=_profiles(),
        passages=_kept()[0],
        report=_web_report if report else None,
    )
    size = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
    typer.echo(
        json.dumps(
            {"snapshot": snapshot_id, **summary, "dir": str(out_dir), "mb": size >> 20}
        )
    )


@app.command()
def publish(
    repo: Annotated[
        Path,
        typer.Option(
            envvar="ACCO_PAGES_REPO", help="Local clone of the GitHub Pages repo"
        ),
    ],
):
    """Stage 11: copy out/site-enc/ into the Pages repo. Never runs git."""
    site_dir = io.path("site-enc")
    try:
        n = accords_site.sync_to_repo(site_dir, repo.expanduser())
    except (ValueError, FileNotFoundError) as e:
        raise typer.BadParameter(str(e)) from e
    typer.echo(
        f"{n} files in {repo}. Keep a single commit (yours to run):\n"
        f"  cd {repo} && git add -A && git commit --amend -m site\n"
        "  git push --force"
    )
