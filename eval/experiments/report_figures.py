"""Figures quoted in eval/generic-to-kali-report.md, recomputed from a run of
generic_to_kali_all.py (default: the latest). Read-only: results.json, the rerank cache and
Elasticsearch (text type and size of the labelled articles). Prints, writes nothing.

    python3 eval/experiments/report_figures.py [eval/runs/generic-to-kali-all-<UTC>]
"""

import json
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "runs"
ES = "http://localhost:9202/chunks/_search"


def pct(a, b):
    return f"{a}/{b} = {100 * a / b:.0f}%" if b else "n/a"


def es(body):
    req = urllib.request.Request(ES, json.dumps(body).encode(), {"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req))["hits"]["hits"]


def main():
    run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(RUNS.glob("generic-to-kali-all-*"))[-1]
    run = json.loads((run_dir / "results.json").read_text())
    ok = [r for r in run["records"] if r["status"] == "ok"]
    print("run", run_dir.name, "| pairs ok", len(ok), "| no label", sum(r["status"] == "no label" for r in run["records"]),
          "| questions", len({r["question_id"] for r in ok}), "| agreements", len({r["idcc"] for r in ok}))
    labels = [(r, a) for r in ok for a in r["labels"]]
    n = len(labels)
    print("labelled articles", n, "| dropped in scored pairs", sum(r["dropped"] for r in ok),
          "| followed", sum(r.get("followed", 0) for r in ok))

    def rank(r, cfg, a):
        return r["ranks"][cfg].get(a)

    def hit(r, cfg, a, k):
        x = rank(r, cfg, a)
        return x is not None and x <= k

    cfgs = list(ok[0]["ranks"])
    print("\n== found@k, all labels")
    for cfg in cfgs:
        print(f"{cfg:14s}", *(pct(sum(hit(r, cfg, a, k) for r, a in labels), n) for k in (5, 7, 10)))

    print("\n== per pair, full knn @5")
    found = [sum(hit(r, "full knn", a, 5) for a in r["labels"]) for r in ok]
    print("at least one", pct(sum(f > 0 for f in found), len(ok)), "| all", pct(sum(f == len(r["labels"]) for f, r in zip(found, ok)), len(ok)))

    print("\n== by number of labels per pair, full knn @5")
    for lo, hi, name in ((1, 1, "1"), (2, 2, "2"), (3, 99, "3+")):
        g = [(r, a) for r, a in labels if lo <= len(r["labels"]) <= hi]
        print(name, pct(sum(hit(r, "full knn", a, 5) for r, a in g), len(g)), "labels", len(g))

    print("\n== by question (full knn @5/@10, hybrid @5, title rerank @5, labels, idcc)")
    byq = defaultdict(list)
    for r in ok:
        byq[r["question"].strip()].append(r)
    rows = []
    for q, rs in byq.items():
        ls = [(r, a) for r in rs for a in r["labels"]]
        f = lambda cfg, k: sum(hit(r, cfg, a, k) for r, a in ls)
        rows.append((f("full knn", 5) / len(ls), q, len(rs), len(ls), f("full knn", 5), f("full knn", 10), f("full hybrid", 5), f("title rerank", 5)))
    rows.sort()
    total_miss = sum(len(r["labels"]) - 0 for r in ok) - sum(hit(r, "full knn", a, 5) for r, a in labels)
    for rec, q, ni, nl, k5, k10, h5, t5 in rows:
        print(f"{100*k5/nl:4.0f}% @5 {100*k10/nl:4.0f}% @10 hyb {100*h5/nl:4.0f}% trr {100*t5/nl:4.0f}% | idcc {ni:2d} labels {nl:3d} per {nl/ni:.1f} | miss share {100*(nl-k5)/total_miss:4.1f}% label share {100*nl/n:4.1f}% | {q[:62]}")
    print("questions >=70% @5:", sum(x[0] >= 0.70 for x in rows), "| >=85%:", sum(x[0] >= 0.85 for x in rows), "of", len(rows))
    top3 = sorted(rows, key=lambda x: x[3] - x[4], reverse=True)[:3]
    print("top-3 miss questions:", [(x[1][:30], round(100 * (x[3] - x[4]) / total_miss)) for x in top3],
          "sum", round(100 * sum(x[3] - x[4] for x in top3) / total_miss))
    sizes = sorted(len(v) for v in byq.values())
    print("pairs per question min/max", sizes[0], sizes[-1], "| >=20:", sum(s >= 20 for s in sizes), "| <=6:", sum(s <= 6 for s in sizes))

    print("\n== hybrid vs knn")
    for cfg in ("full knn", "full hybrid", "full bm25", "title knn", "title hybrid"):
        print(cfg, "labels outside the 64 chunks:", sum(rank(r, cfg, a) is None for r, a in labels))
    for a_, b_ in (("full hybrid", "full knn"), ("title hybrid", "title knn")):
        print(a_, "minus", b_, "@5/@7/@10 points:", [round(100 * (sum(hit(r, a_, a, k) for r, a in labels) - sum(hit(r, b_, a, k) for r, a in labels)) / n, 1) for k in (5, 7, 10)])

    print("\n== reranker (labels found @5, pairs better/worse)")
    for v in ("full", "title"):
        d = sum(hit(r, f"{v} rerank", a, 5) for r, a in labels) - sum(hit(r, f"{v} hybrid", a, 5) for r, a in labels)
        better = worse = 0
        for r in ok:
            x = sum(hit(r, f"{v} rerank", a, 5) for a in r["labels"]); y = sum(hit(r, f"{v} hybrid", a, 5) for a in r["labels"])
            better += x > y; worse += x < y
        print(v, "rerank minus hybrid:", d, "| pairs better", better, "worse", worse)
    print("title rerank minus full knn @5:", sum(hit(r, "title rerank", a, 5) for r, a in labels) - sum(hit(r, "full knn", a, 5) for r, a in labels))
    cache = json.loads((HERE / ".cache" / "rerank.json").read_text())
    sat = sum(sum(s > 0.99 for s in v) >= 20 for v in cache.values())
    print("rerank calls", len(cache), "with >=20 chunks above 0.99:", pct(sat, len(cache)))

    print("\n== full vs title, semantic @5 (pairs that differ)")
    d = Counter()
    for r in ok:
        x = sum(hit(r, "full knn", a, 5) for a in r["labels"]); y = sum(hit(r, "title knn", a, 5) for a in r["labels"])
        d["full better" if x > y else "title better" if y > x else "same"] += 1
    print(dict(d), "differ:", d["full better"] + d["title better"], "of", len(ok))

    print("\n== text type and size (labelled articles; first chunk header)")
    by_idcc = defaultdict(set)
    for r, a in labels:
        by_idcc[r["idcc"]].add(a)
    info = {}
    for idcc, ids in by_idcc.items():
        ids = sorted(ids)
        for i in range(0, len(ids), 25):
            hits = es({"size": 600, "_source": ["content", "metadata.id", "metadata.idx", "metadata.title"],
                       "query": {"bool": {"filter": [{"term": {"metadata.source": "conventions"}}, {"term": {"metadata.idcc": idcc}},
                                                      {"terms": {"metadata.id.keyword": ids[i:i + 25]}}]}}})
            for h in hits:
                m = h["_source"]["metadata"]; c = h["_source"]["content"]
                e = info.setdefault((idcc, m["id"]), {"len": 0, "first": (10**9, ""), "title": m["title"]})
                e["len"] += len(c)
                if (m.get("idx") or 0) < e["first"][0]:
                    e["first"] = (m.get("idx") or 0, c)
    def kind(c):
        c = c.lstrip()
        return "attached" if c.startswith("Textes Attach") else "base" if c.startswith("Texte de base") else "other"
    stats = defaultdict(lambda: [0, 0, 0])
    for r, a in labels:
        e = info.get((r["idcc"], a))
        if not e:
            continue
        s = stats[kind(e["first"][1])]
        s[0] += 1; s[1] += hit(r, "full knn", a, 5); s[2] += rank(r, "full knn", a) is None
    for k, (cnt, h5, miss) in stats.items():
        print(k, "labels", cnt, "found@5", pct(h5, cnt), "not reached", pct(miss, cnt))
    bins = [(0, 1000), (1000, 2000), (2000, 4000), (4000, 8000), (8000, 10**9)]
    for lo, hi in bins:
        g = [(r, a) for r, a in labels if (r["idcc"], a) in info and lo <= info[(r["idcc"], a)]["len"] < hi]
        print(f"size {lo}-{hi}", "labels", len(g), "found@5", pct(sum(hit(r, "full knn", a, 5) for r, a in g), len(g)),
              "not reached", pct(sum(rank(r, "full knn", a) is None for r, a in g), len(g)))
    low = lambda t: ("avenant" in t.lower()) or ("accord" in t.lower())
    lab_titles = [info[(r["idcc"], a)]["title"] for r, a in labels if (r["idcc"], a) in info]
    print("labels with avenant/accord in the title:", pct(sum(low(t) for t in lab_titles), len(lab_titles)))
    html = (HERE.parent / "dataset-explorer.html").read_text()
    import re
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
    art = data["articles"]
    tops = [i for r in ok for i in r["top"]["full knn"][:5]]
    print("top-5 articles (full knn) with avenant/accord in the title:", pct(sum(low(art.get(i, {}).get("t", "")) for i in tops), len(tops)))


if __name__ == "__main__":
    main()
