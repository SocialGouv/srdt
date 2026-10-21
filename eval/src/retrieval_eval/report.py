"""Tables and markdown of a retrieval run: metrics with query-bootstrap intervals by
slice, paired differences between variants, and LLM-vs-human label agreement."""

import itertools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from retrieval_eval.data import Qrel, Query, Ranking
from retrieval_eval.labeller import LabelFailure
from retrieval_eval.metrics import (
    Grades,
    binarise,
    bootstrap_draws,
    confusion_by_cluster,
    exact_agreement,
    mean_with_ci,
    paired_difference,
    percentile_ci,
    query_metrics,
    weighted_kappa,
)

DEFAULT_KS = (5, 10, 20)
HEADLINE = (
    "ndcg@10",
    "recall@10(>=1)",
    "recall@10(>=2)",
    "precision@10(>=1)",
    "mrr(>=1)",
    "judged@10",
)

Slice = Callable[[Query], bool]
SLICES: dict[str, Slice] = {
    "all": lambda q: True,
    "dev": lambda q: q.split == "dev",
    "test": lambda q: q.split == "test",
    "with idcc": lambda q: q.idcc is not None,
    "no idcc": lambda q: q.idcc is None,
    "keyword": lambda q: q.length_bucket == "keyword",
    "short": lambda q: q.length_bucket == "short",
    "detailed": lambda q: q.length_bucket == "detailed",
}


def metric_order(ks: Sequence[int]) -> list[str]:
    return list(query_metrics([], {}, ks))


def per_query_frame(
    rankings: list[Ranking],
    queries: dict[str, Query],
    grades: dict[str, Grades],
    ks: Sequence[int],
) -> pd.DataFrame:
    """One row per (variant, query) for the queries that have at least one label."""
    rows = []
    for ranking in rankings:
        query = queries.get(ranking.query_id)
        if query is None or not grades.get(ranking.query_id):
            continue
        rows.append(
            {
                "variant": ranking.variant,
                "query_id": ranking.query_id,
                "split": query.split,
                "has_idcc": query.idcc is not None,
                "length_bucket": query.length_bucket,
                **query_metrics(ranking.doc_ids, grades[ranking.query_id], ks),
            }
        )
    return pd.DataFrame(rows)


@dataclass
class RetrievalReport:
    metrics: pd.DataFrame  # slice, variant, metric, mean, low, high, n_queries
    pairwise: pd.DataFrame  # slice, a, b, metric, delta, low, high, p_a_better, n
    per_query: pd.DataFrame
    n_queries: dict[str, int]  # slice -> queries with labels
    variants: list[str]


def build_report(
    rankings: list[Ranking],
    queries: dict[str, Query],
    grades: dict[str, Grades],
    ks: Sequence[int] = DEFAULT_KS,
    n_boot: int = 1000,
    seed: int = 0,
    variants: Sequence[str] | None = None,
) -> RetrievalReport:
    frame = per_query_frame(rankings, queries, grades, ks)
    if frame.empty:
        raise ValueError("no ranked query has a label: nothing to report")
    order = list(variants) if variants else sorted(frame["variant"].unique())
    names = metric_order(ks)
    metric_rows, pair_rows, counts = [], [], {}

    for slice_name, belongs in SLICES.items():
        ids = sorted(qid for qid in frame["query_id"].unique() if belongs(queries[qid]))
        if not ids:
            continue
        counts[slice_name] = len(ids)
        # Same draws for every variant of the slice: differences are paired.
        draws = bootstrap_draws(len(ids), n_boot, seed)
        matrix: dict[str, dict[str, np.ndarray]] = {}
        for variant in order:
            part = (
                frame[frame["variant"] == variant]
                .set_index("query_id")
                .reindex(ids)  # a query missing for a variant is undefined for it
            )
            matrix[variant] = {m: part[m].to_numpy(dtype=float) for m in names}
            for metric in names:
                mean, low, high, n = mean_with_ci(matrix[variant][metric], draws)
                metric_rows.append(
                    dict(
                        slice=slice_name,
                        variant=variant,
                        metric=metric,
                        mean=mean,
                        low=low,
                        high=high,
                        n_queries=n,
                    )
                )
        for a, b in itertools.combinations(order, 2):
            for metric in names:
                if metric.startswith("judged@"):
                    continue
                delta, low, high, p = paired_difference(
                    matrix[a][metric], matrix[b][metric], draws
                )
                both = ~(np.isnan(matrix[a][metric]) | np.isnan(matrix[b][metric]))
                pair_rows.append(
                    dict(
                        slice=slice_name,
                        a=a,
                        b=b,
                        metric=metric,
                        delta=delta,
                        low=low,
                        high=high,
                        p_a_better=p,
                        n_queries=int(both.sum()),
                    )
                )
    return RetrievalReport(
        metrics=pd.DataFrame(metric_rows),
        pairwise=pd.DataFrame(pair_rows),
        per_query=frame,
        n_queries=counts,
        variants=order,
    )


# --- agreement ---------------------------------------------------------------


def _pair_key(q: Qrel) -> tuple[str, str, str]:
    return (q.query_id, q.doc_id, q.text_sha256)


def paired_grades(first: list[Qrel], second: list[Qrel]) -> list[tuple[str, int, int]]:
    """(query_id, grade of first, grade of second) for the pairs both labelled on the
    same document text."""
    right = {_pair_key(q): q.grade for q in second}
    return [
        (q.query_id, q.grade, right[_pair_key(q)])
        for q in first
        if _pair_key(q) in right
    ]


def agreement_table(
    reference: list[Qrel],
    other: list[Qrel],
    n_boot: int = 1000,
    seed: int = 0,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Agreement of `other` (e.g. the LLM) with `reference` (e.g. the human) on the
    pairs both labelled, resampling queries. Returns the table and the pooled 3x3
    confusion (rows = reference, columns = other)."""
    pairs = paired_grades(reference, other)
    if not pairs:
        raise ValueError("the two label sets share no (query, document) pair")
    clusters = {qid: i for i, qid in enumerate(sorted({p[0] for p in pairs}))}
    per_cluster = confusion_by_cluster(
        [p[1] for p in pairs],
        [p[2] for p in pairs],
        [clusters[p[0]] for p in pairs],
        len(clusters),
    )
    draws = bootstrap_draws(len(clusters), n_boot, seed)

    def row(name: str, stat: Callable[[np.ndarray], np.ndarray], tables: np.ndarray):
        point = float(stat(tables.sum(axis=0)))
        low, high = percentile_ci(stat(tables[draws].sum(axis=1)))
        return dict(measure=name, value=point, low=low, high=high)

    rows = [
        row("exact agreement", exact_agreement, per_cluster),
        row("kappa (quadratic weights)", weighted_kappa, per_cluster),
        row(
            "kappa, useful or not (grade >= 1)",
            weighted_kappa,
            binarise(per_cluster, 1),
        ),
        row(
            "kappa, answers directly or not (grade >= 2)",
            weighted_kappa,
            binarise(per_cluster, 2),
        ),
    ]
    table = pd.DataFrame(rows)
    table.insert(0, "n_pairs", len(pairs))
    table.insert(1, "n_queries", len(clusters))
    return table, per_cluster.sum(axis=0)


# --- choosing a labeller -------------------------------------------------------

DEFAULT_BAR = (0.6, 0.5)  # kappa on "grade >= 1" and on "grade >= 2"


@dataclass
class CompareResult:
    table: pd.DataFrame  # one row per model
    n_human: int  # pairs labelled by the human
    n_common: int  # of which labelled by every model: what the kappas are on
    n_queries: int
    best: str
    bar: tuple[float, float]
    shortlist: list[str] = field(default_factory=list)  # fastest first
    weighted: bool = False  # the kappas are pool estimates from a stratified sample


def _stats() -> dict[str, Callable[[np.ndarray], np.ndarray]]:
    return {
        "exact": exact_agreement,
        "kappa": weighted_kappa,
        "kappa_ge1": lambda c: weighted_kappa(binarise(c, 1)),
        "kappa_ge2": lambda c: weighted_kappa(binarise(c, 2)),
    }


def compare_labellers(
    human: list[Qrel],
    models: dict[str, list[Qrel]],
    failures: dict[str, list[LabelFailure]] | None = None,
    n_boot: int = 1000,
    seed: int = 0,
    bar: tuple[float, float] = DEFAULT_BAR,
    weights: dict[tuple[str, str, str], float] | None = None,
) -> CompareResult:
    """Agreement of several labellers with one human, on the pairs all of them labelled.

    A model is *eligible* if its kappa reaches `bar` on "useful or not" (grade >= 1)
    and on "answers directly or not" (grade >= 2) (point estimates; `lower_ok` says
    whether the lower interval bounds do too). It is *shortlisted* if it is eligible
    and its paired kappa difference against the best model (by 3-grade weighted
    kappa) has an interval containing 0. Within the shortlist, models are listed
    fastest first: price is not known here, so the cost call is the reader's.

    `weights` (pair -> number of pool pairs it stands for) is given when the human
    pairs are a stratified sample: only the pairs it lists are used, the kappas and
    their intervals then estimate the pool's, and the unweighted kappas of the sample
    are kept in `*_raw` columns.
    """
    failures = failures or {}
    human_by_key = {
        _pair_key(q): q.grade
        for q in human
        if weights is None or _pair_key(q) in weights
    }
    if not human_by_key:
        raise ValueError("no human labels to compare with")
    by_model = {
        name: {_pair_key(q): q for q in qrels if _pair_key(q) in human_by_key}
        for name, qrels in models.items()
    }
    common = set(human_by_key)
    for labelled in by_model.values():
        common &= set(labelled)
    if not common:
        raise ValueError("no pair is labelled by the human and by every model")

    clusters = {qid: i for i, qid in enumerate(sorted({k[0] for k in common}))}
    draws = bootstrap_draws(len(clusters), n_boot, seed)
    ordered = sorted(common)
    stats = _stats()

    rows, point, boot = [], {}, {}
    for name, labelled in by_model.items():
        per_cluster = confusion_by_cluster(
            [human_by_key[k] for k in ordered],
            [labelled[k].grade for k in ordered],
            [clusters[k[0]] for k in ordered],
            len(clusters),
            None if weights is None else [weights[k] for k in ordered],
        )
        pooled = per_cluster.sum(axis=0)
        raw = (
            pooled
            if weights is None
            else confusion_by_cluster(
                [human_by_key[k] for k in ordered],
                [labelled[k].grade for k in ordered],
                [clusters[k[0]] for k in ordered],
                len(clusters),
            ).sum(axis=0)
        )
        row: dict = {"model": name}
        for stat_name in ("kappa", "kappa_ge1", "kappa_ge2"):
            row[f"{stat_name}_raw"] = float(stats[stat_name](raw))
        for stat_name, stat in stats.items():
            point[name, stat_name] = float(stat(pooled))
            boot[name, stat_name] = stat(per_cluster[draws].sum(axis=1))
            low, high = percentile_ci(boot[name, stat_name])
            row[stat_name] = point[name, stat_name]
            row[f"{stat_name}_low"], row[f"{stat_name}_high"] = low, high
        total = pooled.sum()
        row["over_graded"] = float(np.triu(pooled, 1).sum() / total)
        row["under_graded"] = float(np.tril(pooled, -1).sum() / total)

        mine = list(labelled.values())
        latencies = [q.latency_s for q in mine if q.latency_s is not None]
        prompt = [q.prompt_tokens for q in mine if q.prompt_tokens is not None]
        completion = [q.completion_tokens for q in mine if q.completion_tokens]
        failed = {
            (f.status, _pair_key(f))
            for f in failures.get(name, [])
            if _pair_key(f) in human_by_key and _pair_key(f) not in labelled
        }
        row.update(
            coverage=len(labelled) / len(human_by_key),
            parse_errors=sum(status == "parse_error" for status, _ in failed),
            api_errors=sum(status == "api_error" for status, _ in failed),
            latency_p50=float(np.percentile(latencies, 50)) if latencies else math.nan,
            latency_p95=float(np.percentile(latencies, 95)) if latencies else math.nan,
            prompt_tokens=float(np.mean(prompt)) if prompt else math.nan,
            completion_tokens=float(np.mean(completion)) if completion else math.nan,
        )
        rows.append(row)

    table = pd.DataFrame(rows)
    ranked = table["kappa"].fillna(-math.inf)
    best = str(table.loc[ranked.idxmax(), "model"])
    deltas = []
    for name in table["model"]:
        if name == best:
            deltas.append((0.0, 0.0, 0.0, math.nan))
            continue
        diff = boot[name, "kappa"] - boot[best, "kappa"]
        low, high = percentile_ci(diff)
        finite = diff[np.isfinite(diff)]
        deltas.append(
            (
                point[name, "kappa"] - point[best, "kappa"],
                low,
                high,
                float((finite > 0).mean()) if finite.size else math.nan,
            )
        )
    table["delta_kappa"], table["delta_low"], table["delta_high"], table["p_better"] = (
        zip(*deltas, strict=True)
    )
    useful, direct = bar
    table["eligible"] = (table["kappa_ge1"] >= useful) & (table["kappa_ge2"] >= direct)
    table["lower_ok"] = (table["kappa_ge1_low"] >= useful) & (
        table["kappa_ge2_low"] >= direct
    )
    table["eligible_raw"] = (table["kappa_ge1_raw"] >= useful) & (
        table["kappa_ge2_raw"] >= direct
    )
    within_noise = (table["model"] == best) | (
        (table["delta_low"] <= 0) & (table["delta_high"] >= 0)
    )
    table["shortlisted"] = table["eligible"] & within_noise
    shortlist = (
        table[table["shortlisted"]]
        .sort_values("latency_p50", na_position="last")["model"]
        .tolist()
    )
    return CompareResult(
        table=table,
        n_human=len(human_by_key),
        n_common=len(common),
        n_queries=len(clusters),
        best=best,
        bar=bar,
        shortlist=shortlist,
        weighted=weights is not None,
    )


# --- error profile of a labeller ---------------------------------------------

PROFILE_VIEWS = {  # derived binary views of the 0/1/2 grades, for metrics only
    "useful (grade >= 1 vs 0)": 1,
    "answers directly (grade 2 vs below)": 2,
}


@dataclass
class LabellerProfile:
    table: pd.DataFrame  # section, measure, value, low, high
    confusion: np.ndarray  # 3x3, rows = human grade, columns = labeller grade
    n_pairs: int
    n_queries: int
    weighted: bool


def _binary_scores(c: np.ndarray) -> dict[str, np.ndarray]:
    """Scores of (..., 2, 2) tables: rows human (0 False, 1 True), columns labeller."""
    tn, fp, fn, tp = c[..., 0, 0], c[..., 0, 1], c[..., 1, 0], c[..., 1, 1]
    n = tn + fp + fn + tp
    with np.errstate(invalid="ignore", divide="ignore"):
        precision, recall = tp / (tp + fp), tp / (tp + fn)
        observed = (tp + tn) / n
        chance = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / n**2
        mcc = (tp * tn - fp * fn) / np.sqrt(
            (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
        )
        return {
            "accuracy": observed,
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall),
            "kappa": (observed - chance) / (1 - chance),
            "mcc": mcc,
            "labeller says True": (tp + fp) / n,
            "human says True": (tp + fn) / n,
        }


def _graded_scores(c: np.ndarray) -> dict[str, np.ndarray]:
    """Scores of (..., 3, 3) tables: rows human grade, columns labeller grade."""
    total = c.sum(axis=(-2, -1))
    with np.errstate(invalid="ignore", divide="ignore"):
        scores = {
            "exact agreement": exact_agreement(c),
            "kappa (quadratic weights)": weighted_kappa(c),
            "labeller grades higher than the human": np.triu(c, 1).sum(axis=(-2, -1))
            / total,
            "labeller grades lower than the human": np.tril(c, -1).sum(axis=(-2, -1))
            / total,
        }
        for g in range(3):
            diagonal = c[..., g, g]
            scores[f"grade {g}: precision (labeller says {g}, human agrees)"] = (
                diagonal / c[..., :, g].sum(axis=-1)
            )
            scores[f"grade {g}: recall (human says {g}, labeller agrees)"] = (
                diagonal / c[..., g, :].sum(axis=-1)
            )
    return scores


def labeller_profile(
    human: list[Qrel],
    labeller: list[Qrel],
    weights: dict[tuple[str, str, str], float] | None = None,
    n_boot: int = 1000,
    seed: int = 0,
) -> LabellerProfile:
    """How a labeller errs against a human, on the pairs both graded.

    The profile is graded first (3x3 confusion, exact agreement, quadratic-weighted
    kappa, who grades higher, precision and recall of each grade), then gives two
    derived binary views for reading the metrics: 'useful' (grade >= 1) and 'answers
    directly' (grade 2). `weights` (pair -> pool pairs it stands for) makes every
    figure an estimate for the pool when the human pairs are a stratified sample; only
    the pairs it lists are used. Intervals resample whole queries."""
    mine = {_pair_key(q): q.grade for q in labeller}
    human_by_key = {
        _pair_key(q): q.grade
        for q in human
        if _pair_key(q) in mine and (weights is None or _pair_key(q) in weights)
    }
    if not human_by_key:
        raise ValueError("the human and the labeller share no (query, document) pair")
    keys = sorted(human_by_key)
    clusters = {qid: i for i, qid in enumerate(sorted({k[0] for k in keys}))}
    per_cluster = confusion_by_cluster(
        [human_by_key[k] for k in keys],
        [mine[k] for k in keys],
        [clusters[k[0]] for k in keys],
        len(clusters),
        None if weights is None else [weights[k] for k in keys],
    )
    draws = bootstrap_draws(len(clusters), n_boot, seed)
    pooled = per_cluster.sum(axis=0)

    rows = []

    def add(section: str, point: dict, boot: dict) -> None:
        for measure, value in point.items():
            low, high = percentile_ci(boot[measure])
            rows.append(
                dict(
                    section=section,
                    measure=measure,
                    value=float(value),
                    low=low,
                    high=high,
                )
            )

    add(
        "graded", _graded_scores(pooled), _graded_scores(per_cluster[draws].sum(axis=1))
    )
    for view, threshold in PROFILE_VIEWS.items():
        binary = binarise(per_cluster, threshold)
        add(
            view,
            _binary_scores(binary.sum(axis=0)),
            _binary_scores(binary[draws].sum(axis=1)),
        )
    return LabellerProfile(
        table=pd.DataFrame(rows),
        confusion=pooled,
        n_pairs=len(keys),
        n_queries=len(clusters),
        weighted=weights is not None,
    )


# --- rendering ---------------------------------------------------------------


def _num(value: float) -> str:
    return "-" if value is None or math.isnan(value) else f"{value:.3f}"


def _ci(mean: float, low: float, high: float) -> str:
    if math.isnan(mean):
        return "-"
    return f"{mean:.3f} [{_num(low)}, {_num(high)}]"


def _markdown_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def render_markdown(
    report: RetrievalReport, n_boot: int, context: dict[str, str] | None = None
) -> str:
    out = ["# Retrieval evaluation", ""]
    for key, value in (context or {}).items():
        out.append(f"- {key}: {value}")
    out += [
        "",
        f"Intervals are 95% percentile intervals over {n_boot} resamples of whole "
        "queries (variants share the draws). A document without a label counts as "
        "not relevant, so `judged@10` (the share of the top 10 that has a label) "
        "bounds how much the other numbers can move: read a low value as 'scores "
        "are lower bounds'. Recall, precision, MRR and nDCG skip queries with no "
        "relevant document at the threshold; `n` is the number of queries left.",
        "",
    ]
    metrics = report.metrics
    for slice_name, count in report.n_queries.items():
        out += [f"## {slice_name} ({count} queries with labels)", ""]
        part = metrics[metrics["slice"] == slice_name]
        rows = []
        for variant in report.variants:
            cells = []
            for metric in HEADLINE:
                hit = part[(part["variant"] == variant) & (part["metric"] == metric)]
                if hit.empty:
                    cells.append("-")
                    continue
                r = hit.iloc[0]
                text = _ci(r["mean"], r["low"], r["high"])
                if not metric.startswith("judged@") and r["n_queries"] != count:
                    text += f" n={int(r['n_queries'])}"
                cells.append(text)
            rows.append([variant, *cells])
        out += [_markdown_table(["variant", *HEADLINE], rows), ""]

    pairwise = report.pairwise
    if not pairwise.empty:
        out += ["## Paired differences (all queries)", ""]
        part = pairwise[
            (pairwise["slice"] == "all") & (pairwise["metric"].isin(HEADLINE))
        ]
        rows = [
            [
                f"{r['a']} - {r['b']}",
                r["metric"],
                _ci(r["delta"], r["low"], r["high"]),
                _num(r["p_a_better"]),
                str(int(r["n_queries"])),
            ]
            for _, r in part.iterrows()
        ]
        out += [
            _markdown_table(["pair", "metric", "delta", "P(a > b)", "n"], rows),
            "",
        ]
    return "\n".join(out)


def render_agreement(
    table: pd.DataFrame, confusion: np.ndarray, reference: str, other: str
) -> str:
    first = table.iloc[0]
    rows = [
        [r["measure"], _ci(r["value"], r["low"], r["high"])]
        for _, r in table.iterrows()
    ]
    matrix = [
        [f"{reference} = {g}", *[str(int(c)) for c in confusion[g]]] for g in range(3)
    ]
    return "\n".join(
        [
            f"# Agreement of {other} with {reference}",
            "",
            f"{int(first['n_pairs'])} pairs over {int(first['n_queries'])} queries "
            "(intervals resample queries).",
            "",
            _markdown_table(["measure", "value [95% CI]"], rows),
            "",
            f"Confusion (rows {reference}, columns {other}):",
            "",
            _markdown_table(
                ["", f"{other} = 0", f"{other} = 1", f"{other} = 2"], matrix
            ),
            "",
        ]
    )


def render_compare(result: CompareResult, n_boot: int) -> str:
    table = result.table
    useful, direct = result.bar
    rows = []
    for _, r in table.sort_values("kappa", ascending=False).iterrows():
        rows.append(
            [
                r["model"],
                f"{r['coverage']:.0%}",
                f"{int(r['parse_errors'])} / {int(r['api_errors'])}",
                _ci(r["kappa_ge1"], r["kappa_ge1_low"], r["kappa_ge1_high"]),
                _ci(r["kappa_ge2"], r["kappa_ge2_low"], r["kappa_ge2_high"]),
                _ci(r["kappa"], r["kappa_low"], r["kappa_high"]),
                "best"
                if r["model"] == result.best
                else _ci(r["delta_kappa"], r["delta_low"], r["delta_high"]),
                f"{_num(r['kappa_ge1_raw'])} / {_num(r['kappa_ge2_raw'])}",
                f"{r['over_graded']:.0%} / {r['under_graded']:.0%}",
                _num(r["latency_p50"]),
                _num(r["prompt_tokens"] / 1000)
                if r["prompt_tokens"] == r["prompt_tokens"]
                else "-",
                ("yes" if r["lower_ok"] else "yes (point)") if r["eligible"] else "no",
                "**yes**" if r["shortlisted"] else "",
            ]
        )
    header = [
        "model",
        "coverage",
        "parse / API errors",
        "kappa, useful (>= 1)",
        "kappa, direct (>= 2)",
        "kappa, 3 grades",
        "paired diff vs best",
        "sample kappa >= 1 / >= 2, unweighted",
        "over / under-graded",
        "latency p50 s",
        "prompt k tokens",
        "eligible",
        "shortlisted",
    ]
    if result.shortlist:
        verdict = (
            "Shortlist, fastest first: "
            + ", ".join(f"`{m}`" for m in result.shortlist)
            + ". Choose among them on cost and provider; they cannot be told apart "
            "on agreement with this sample."
        )
    else:
        verdict = (
            "**No model reaches the bar.** Do not pick the least bad one: fix the "
            "guideline, or use the majority of three models, then compare again."
        )
    return "\n".join(
        [
            "# Choosing the labeller",
            "",
            f"{result.n_common} pairs over {result.n_queries} queries, labelled by the "
            f"human and by every model ({result.n_human} human-labelled pairs in all). "
            f"Intervals are 95% percentile intervals over {n_boot} resamples of whole "
            "queries; models share the draws, so the paired differences are paired.",
            "",
            f"Bar fixed beforehand: kappa >= {useful} on 'useful or not' (grade >= 1) "
            f"and >= {direct} on 'answers directly or not' (grade >= 2), point "
            "estimates ('yes' alone: the lower interval bounds reach it too). "
            "Shortlisted = eligible, and the paired kappa difference against the best "
            "model has an interval containing 0.",
            "",
            _markdown_table(header, rows),
            "",
            verdict,
            "",
            *(
                [
                    "**The bar gives different verdicts on the unweighted sample for: "
                    + ", ".join(
                        f"`{m}`"
                        for m in table[table["eligible"] != table["eligible_raw"]][
                            "model"
                        ]
                    )
                    + ".** The pool-weighted estimate is the one that counts; read the "
                    "gap as a sign that the result rests on few pairs.",
                    "",
                ]
                if result.weighted
                and (table["eligible"] != table["eligible_raw"]).any()
                else []
            ),
            *(
                [
                    "The pairs were drawn by strata and each stands for the pool pairs "
                    "of its stratum: kappas, intervals and the bar are on the "
                    "**pool-weighted** estimate. The unweighted kappas of the sample "
                    "itself are in their own column, for reference.",
                    "",
                ]
                if result.weighted
                else []
            ),
            "Kappas are on the pairs every model labelled; coverage is over all the "
            "human-labelled pairs, and a model with a low coverage is penalised there, "
            "not in the kappa.",
            "",
        ]
    )


def render_profile(profile: LabellerProfile, labeller: str, human: str) -> str:
    out = [
        f"## Labeller error profile: {labeller} against {human}",
        "",
        f"{profile.n_pairs} human-graded pairs over {profile.n_queries} queries"
        + (
            ", each weighted by the pool pairs it stands for (the figures estimate "
            "the pool)"
            if profile.weighted
            else ""
        )
        + ". Intervals are 95% percentile intervals over resamples of whole queries. "
        "Labels are graded 0/1/2; the two binary views below only exist to read the "
        "metrics (precision, recall, kappa) and state their threshold.",
        "",
        f"Confusion (rows {human}, columns {labeller}"
        + (", in pool pairs" if profile.weighted else "")
        + "):",
        "",
        _markdown_table(
            ["", f"{labeller} = 0", f"{labeller} = 1", f"{labeller} = 2"],
            [
                [
                    f"{human} = {g}",
                    *[f"{profile.confusion[g, j]:.0f}" for j in range(3)],
                ]
                for g in range(3)
            ],
        ),
        "",
    ]
    for section in profile.table["section"].unique():
        part = profile.table[profile.table["section"] == section]
        title = "Graded (0/1/2)" if section == "graded" else f"Binary view: {section}"
        out += [
            f"### {title}",
            "",
            _markdown_table(
                ["measure", "value [95% CI]"],
                [
                    [r["measure"], _ci(r["value"], r["low"], r["high"])]
                    for _, r in part.iterrows()
                ],
            ),
            "",
        ]
    return "\n".join(out)
