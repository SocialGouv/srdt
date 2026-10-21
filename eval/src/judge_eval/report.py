"""Turns a run's predictions into tables: metrics, paired comparisons, per-question
breakdown and the list of disagreements with the human labels."""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

from judge_eval.baselines import PREFIX
from judge_eval.data import CRITERIA, Criterion, Item
from judge_eval.metrics import (
    bootstrap_scores,
    cluster_counts,
    percentile_ci,
    scores,
)
from judge_eval.runner import Prediction


@dataclass(frozen=True)
class Slice:
    """A criterion, optionally restricted to answers the humans found correct."""

    name: str
    criterion: Criterion
    only_human_correct: bool = False
    # Baselines that stop making sense on the subset (see SLICES).
    exclude_judges: tuple[str, ...] = ()


SLICES: tuple[Slice, ...] = (
    *(Slice(c.value, c) for c in CRITERIA),
    # `suffisant` is almost implied by `correct_en_droit` in the human labels
    # (84 % identical); this keeps only the answers where it carries information.
    # The global majority label and the copy of `correct_en_droit` (always "Oui"
    # here) are meaningless on this subset; its majority accuracy is printed in
    # the report instead.
    Slice(
        "suffisant | correct=Oui",
        Criterion.SUFFISANT,
        only_human_correct=True,
        exclude_judges=(PREFIX + "majority", PREFIX + "copy-correct"),
    ),
)


def build_frame(
    items: Sequence[Item], predictions: Sequence[Prediction]
) -> pd.DataFrame:
    by_id = {i.id: i for i in items}
    rows = []
    for p in predictions:
        item = by_id.get(p.item_id)
        if item is None:
            continue
        rows.append(
            {
                "judge": p.judge,
                "criterion": p.criterion.value,
                "item_id": p.item_id,
                "question_id": item.question_id,
                "valid": p.status == "ok",
                "status": p.status,
                "human": item.labels[p.criterion],
                "pred": bool(p.label) if p.label is not None else False,
                "human_correct": item.labels[Criterion.CORRECT_EN_DROIT],
                "latency_s": p.latency_s,
                "prompt_tokens": p.prompt_tokens,
                "completion_tokens": p.completion_tokens,
                "reasoning": p.reasoning,
                "error": p.error,
            }
        )
    df = pd.DataFrame(
        rows,
        columns=[
            "judge", "criterion", "item_id", "question_id", "valid", "status",
            "human", "pred", "human_correct", "latency_s", "prompt_tokens",
            "completion_tokens", "reasoning", "error",
        ],
    )  # fmt: skip
    for column in ("valid", "human", "pred", "human_correct"):
        df[column] = df[column].astype(bool)
    for column in ("latency_s", "prompt_tokens", "completion_tokens"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def _slice_rows(df: pd.DataFrame, s: Slice) -> pd.DataFrame:
    rows = df[
        (df["criterion"] == s.criterion.value) & ~df["judge"].isin(s.exclude_judges)
    ]
    return rows[rows["human_correct"]] if s.only_human_correct else rows


def _judge_order(df: pd.DataFrame) -> list[str]:
    judges = sorted(df["judge"].unique())
    return [j for j in judges if j.startswith(PREFIX)] + [
        j for j in judges if not j.startswith(PREFIX)
    ]


def metrics_table(df: pd.DataFrame, n_clusters: int, draws: np.ndarray) -> pd.DataFrame:
    records = []
    for s in SLICES:
        sliced = _slice_rows(df, s)
        for judge in _judge_order(df):
            rows = sliced[sliced["judge"] == judge]
            if rows.empty:
                continue
            valid = rows[rows["valid"]]
            per_cluster = cluster_counts(
                valid["human"].to_numpy(),
                valid["pred"].to_numpy(),
                valid["question_id"].to_numpy(),
                n_clusters,
            )
            point = {k: float(v) for k, v in scores(per_cluster.sum(axis=0)).items()}
            boot = bootstrap_scores(per_cluster, draws)
            acc_lo, acc_hi = percentile_ci(boot["accuracy"])
            kappa_lo, kappa_hi = percentile_ci(boot["kappa"])
            latency = rows["latency_s"].dropna()
            records.append(
                {
                    "slice": s.name,
                    "judge": judge,
                    "n_total": len(rows),
                    "n_valid": len(valid),
                    "coverage": len(valid) / len(rows),
                    "parse_errors": int((rows["status"] == "parse_error").sum()),
                    "api_errors": int((rows["status"] == "api_error").sum()),
                    "human_oui_rate": float(valid["human"].mean())
                    if len(valid)
                    else np.nan,
                    "pred_oui_rate": float(valid["pred"].mean())
                    if len(valid)
                    else np.nan,
                    **point,
                    "accuracy_lo": acc_lo,
                    "accuracy_hi": acc_hi,
                    "kappa_lo": kappa_lo,
                    "kappa_hi": kappa_hi,
                    "latency_p50_s": float(latency.quantile(0.5))
                    if len(latency)
                    else np.nan,
                    "latency_p95_s": float(latency.quantile(0.95))
                    if len(latency)
                    else np.nan,
                    "prompt_tokens_mean": float(rows["prompt_tokens"].mean()),
                    "completion_tokens_mean": float(rows["completion_tokens"].mean()),
                    "tp": int(per_cluster[:, 0].sum()),
                    "fp": int(per_cluster[:, 1].sum()),
                    "fn": int(per_cluster[:, 2].sum()),
                    "tn": int(per_cluster[:, 3].sum()),
                }
            )
    return pd.DataFrame(records)


def pairwise_table(
    df: pd.DataFrame, n_clusters: int, draws: np.ndarray
) -> pd.DataFrame:
    """Paired kappa difference between every two non-baseline judges, on the
    answers both judged validly, resampling the same questions for both."""
    judges = [j for j in _judge_order(df) if not j.startswith(PREFIX)]
    records = []
    for s in SLICES:
        sliced = _slice_rows(df, s)
        for a, b in combinations(judges, 2):
            ra = sliced[(sliced["judge"] == a) & sliced["valid"]].set_index("item_id")
            rb = sliced[(sliced["judge"] == b) & sliced["valid"]].set_index("item_id")
            common = ra.index.intersection(rb.index)
            if common.empty:
                continue
            ra, rb = ra.loc[common], rb.loc[common]
            qids = ra["question_id"].to_numpy()
            ca = cluster_counts(
                ra["human"].to_numpy(), ra["pred"].to_numpy(), qids, n_clusters
            )
            cb = cluster_counts(
                rb["human"].to_numpy(), rb["pred"].to_numpy(), qids, n_clusters
            )
            sa, sb = scores(ca.sum(axis=0)), scores(cb.sum(axis=0))
            delta_boot = (
                bootstrap_scores(ca, draws)["kappa"]
                - bootstrap_scores(cb, draws)["kappa"]
            )
            lo, hi = percentile_ci(delta_boot)
            finite = delta_boot[np.isfinite(delta_boot)]
            records.append(
                {
                    "slice": s.name,
                    "judge_a": a,
                    "judge_b": b,
                    "n_common": len(common),
                    "delta_accuracy": float(sa["accuracy"] - sb["accuracy"]),
                    "delta_kappa": float(sa["kappa"] - sb["kappa"]),
                    "delta_kappa_lo": lo,
                    "delta_kappa_hi": hi,
                    "p_a_better": float((finite > 0).mean()) if finite.size else np.nan,
                }
            )
    return pd.DataFrame(records)


def per_question_table(df: pd.DataFrame) -> pd.DataFrame:
    valid = df[df["valid"]].copy()
    valid["correct"] = valid["human"] == valid["pred"]
    grouped = valid.groupby(["criterion", "judge", "question_id"])
    return grouped.agg(
        n=("correct", "size"),
        accuracy=("correct", "mean"),
        human_oui_rate=("human", "mean"),
        pred_oui_rate=("pred", "mean"),
    ).reset_index()


def disagreements_table(df: pd.DataFrame, items: Sequence[Item]) -> pd.DataFrame:
    by_id = {i.id: i for i in items}
    wrong = df[df["valid"] & (df["human"] != df["pred"])].copy()
    wrong["question"] = wrong["item_id"].map(lambda i: by_id[i].question)
    wrong["answer"] = wrong["item_id"].map(lambda i: by_id[i].answer)
    wrong["human"] = wrong["human"].map({True: "Oui", False: "Non"})
    wrong["pred"] = wrong["pred"].map({True: "Oui", False: "Non"})
    columns = [
        "judge", "criterion", "item_id", "question_id", "human", "pred",
        "reasoning", "question", "answer",
    ]  # fmt: skip
    return wrong[columns].sort_values(["judge", "criterion", "question_id", "item_id"])


# --- Markdown ------------------------------------------------------------


def _pct(x: float) -> str:
    return "–" if pd.isna(x) else f"{x * 100:.1f}"


def _num(x: float, digits: int = 2) -> str:
    return "–" if pd.isna(x) else f"{x:.{digits}f}"


def _ci(value: float, lo: float, hi: float, fmt) -> str:
    return f"{fmt(value)} [{fmt(lo)}, {fmt(hi)}]"


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def render_markdown(
    metrics: pd.DataFrame,
    pairwise: pd.DataFrame,
    *,
    run_name: str,
    n_clusters: int,
    n_boot: int,
) -> str:
    out = [
        f"# Judge evaluation: {run_name}",
        "",
        "Agreement between each judge and the human labels. Positive class = "
        '"Oui". "Non P/R/F1" is the detection of answers humans rejected. '
        f"95 % CIs: bootstrap resampling the {n_clusters} questions "
        f"({n_boot} draws); with so few questions they are wide, so small gaps "
        "between judges are not meaningful. Metrics use valid verdicts only: check "
        "`valid` before trusting them.",
        "",
        "`baseline:*` rows are reference lines built from the human labels "
        "(majority class; answer length, threshold fitted in-sample; for `suffisant`, "
        "copy of the human `correct_en_droit`), not real judges.",
    ]
    for s in SLICES:
        rows = metrics[metrics["slice"] == s.name]
        if rows.empty:
            continue
        first = rows.iloc[0]
        out += ["", f"## {s.name}", ""]
        rate = first["human_oui_rate"]
        majority_accuracy = max(rate, 1 - rate)
        out.append(
            f'Human "Oui" rate on judged answers: {_pct(rate)} % '
            f"(always answering the majority label scores "
            f"{_pct(majority_accuracy)} %)"
        )
        out.append("")
        table = []
        for r in rows.itertuples():
            table.append(
                [
                    r.judge,
                    f"{r.n_valid}/{r.n_total}",
                    _ci(
                        r.accuracy * 100,
                        r.accuracy_lo * 100,
                        r.accuracy_hi * 100,
                        lambda v: _num(v, 1),
                    ),
                    _pct(r.balanced_accuracy),
                    _ci(r.kappa, r.kappa_lo, r.kappa_hi, _num),
                    _num(r.mcc),
                    " / ".join(
                        _pct(v) for v in (r.non_precision, r.non_recall, r.non_f1)
                    ),
                    _pct(r.pred_oui_rate),
                    f"{_num(r.latency_p50_s, 1)} / {_num(r.latency_p95_s, 1)}",
                ]
            )
        out.append(
            _markdown_table(
                [
                    "judge",
                    "valid",
                    "accuracy % [CI]",
                    "bal. acc %",
                    "κ [CI]",
                    "MCC",
                    "Non P / R / F1 %",
                    "pred Oui %",
                    "latency p50 / p95 s",
                ],
                table,
            )  # fmt: skip
        )
    if not pairwise.empty:
        out += ["", "## Paired comparison between judges (Δκ = A − B)", ""]
        table = [
            [
                r.slice,
                r.judge_a,
                r.judge_b,
                str(r.n_common),
                _num(r.delta_kappa),
                f"[{_num(r.delta_kappa_lo)}, {_num(r.delta_kappa_hi)}]",
                _pct(r.p_a_better),
            ]
            for r in pairwise.itertuples()
        ]
        out.append(
            _markdown_table(
                ["slice", "A", "B", "n", "Δκ", "95 % CI", "P(A better) %"], table
            )
        )
    return "\n".join(out) + "\n"
