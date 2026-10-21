# Web checks: log

What `web-snapshot` / `web-check` found against production, one entry per check, newest
last. The snapshots are under `runs/retrieval-1/web_snapshots/` (gitignored, local to
the machine that ran them): keep the baseline folder named below, the next check is
compared with it.

## 2026-10-20: baseline

- Web `https://web-srdt.fabrique.social.gouv.fr`, API `https://api-srdt.fabrique.social.gouv.fr`,
  repo at `6c9396f` (feat/eval rebased on main 1.57.0: fiches in rerank order,
  jurisprudence LLM filter).
- Queries: the 22 `idcc22` queries. Stored run: `retrieval-1` (pooled 2026-10-19).
- Snapshots: `20261020T124033Z` (20/22 web responses, 2 failed), and
  `20261020T125140Z` (22/22), **the baseline**.

Results of `20261020T125140Z`:

| check | result |
|---|---|
| parity (web vs port, same minute) | 19/22 identical top 10 (+contributions), mean overlap@10 0.99 |
| drift vs `retrieval-1`, same text | 14/17 identical, mean overlap@10 0.99 |
| anonymize changed the text | 5 queries, drift not counted: q_e34e9fa3, q_11faa7f0, q_6747dba4, q_72665834, q_c2de0798 |

The 3 parity differences are reranker noise, not a port bug: each one flips between
the two snapshots, on the web side and on the port side alike.

- q_8bfd1d04, ranks 3/4 swapped: `4e7740…` and `86de7c…` have exactly the same rerank
  score (0.58338) and come back in either order.
- q_baeae0ac, rank 9: the reranker scored `b9c2c2…` 0.43350 in one call, 0.53163 in
  another (it then enters the top 10).
- q_89f32268, rank 10: the port's top 10 is the same in 3 runs; the web's rank 10 was
  `384f7a…` (as the port) in one snapshot, `30e666…` in the other. The route does not
  return the fiches' scores, so this one is not proven, only likely.

Noise between the two snapshots (11 minutes apart, 20 queries, `compare_snapshots`):
fiches identical 17/20 (q_baeae0ac rank 9, q_89f32268 rank 10, q_1080ba2a rank 1),
`contributions` 20/20, code du travail 19/20, jurisprudence 20/20, anonymized text 20/20.
**A later check showing about this much drift shows no change.**

### Next check

```sh
uv run retrieval-eval web-snapshot --run-id retrieval-1 --source idcc22
uv run retrieval-eval web-check --run-id retrieval-1                               # parity + drift vs retrieval-1
uv run retrieval-eval web-check --run-id retrieval-1 --against 20261020T125140Z    # drift vs the baseline
```

Without the web (no LLM call, the API only, the same anonymization as production):

```sh
uv run retrieval-eval web-snapshot --run-id retrieval-1 --source idcc22 --port-only
uv run retrieval-eval web-check --run-id retrieval-1 --against 20261020T125140Z    # vs the baseline's port rankings
```

This shows whether the API (index, reranker, `/anonymize`) still returns the same
results; it does not check the web code. Baseline noise for the port: between the two
snapshots of 2026-10-20 its top 10 was identical for 18/20 queries (q_baeae0ac rank 9,
q_8bfd1d04 tied ranks 3/4).

The second command writes `report.md` in the new snapshot, the third
`report-vs-20261020T125140Z.md`. A failed query is redone with `web-snapshot ...
--resume <new timestamp>`. Read the result against the noise above: differences at
ranks 9-10 or between tied scores are expected; a change of many top 10s, of
`contributions`, or of the anonymized text means something changed in production.
Add the result as a new entry below.
