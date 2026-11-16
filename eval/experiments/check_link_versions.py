"""Which of the editors' KALI links cite an outdated version of an article?

In KALI an article gets a new id (a new version) each time it is amended and keeps a stable
`cid`; a link written years ago may point to a version that has since been replaced. The
KALI snapshot only holds the current versions, so it cannot tell. The Légifrance API
(PISTE, `consult/getArticle`) returns for any article id its state and the list of its
versions, which does.

For each distinct KALIARTI id cited by the contributions (read from the data embedded in
dataset-explorer.html, i.e. the same links the explorer shows) the script stores:
current (the cited version is in force), replaced (a later version is in force; its id is
kept), abrogated, or other / error. Read-only calls, cached on disk, results in
eval/runs/link-versions-<UTC>/results.json. Credentials: PISTE_* in ingestion/.env.

    cd ingestion && .venv/bin/python ../eval/experiments/check_link_versions.py
"""

import json
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

HERE = Path(__file__).resolve().parent
EXPLORER = HERE.parent / "dataset-explorer.html"
CACHE = HERE / ".cache" / "legifrance_articles.json"
RUNS = HERE.parent / "runs"
ENV = Path(".env")
OPEN_END_MS = 32_000_000_000_000  # Légifrance uses year 2999/3000 for "no end date"
IN_FORCE = {"VIGUEUR", "VIGUEUR_ETEN", "VIGUEUR_NON_ETEN"}
PAUSE = 0.15


class Retryable(Exception):
    pass


class Piste:
    def __init__(self, env: dict[str, str]):
        self.env = env
        self.http = httpx.Client(timeout=30)
        self.token = ""

    def login(self) -> None:
        r = self.http.post(self.env["PISTE_TOKEN_HOST"], data={
            "grant_type": "client_credentials",
            "client_id": self.env["PISTE_OAUTH_CLIENT_ID"],
            "client_secret": self.env["PISTE_OAUTH_CLIENT_SECRET"],
            "scope": "openid",
        })
        r.raise_for_status()
        self.token = r.json()["access_token"]

    @retry(
        retry=retry_if_exception_type(Retryable),
        wait=wait_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(6),
        reraise=True,
    )
    def article(self, article_id: str) -> dict:
        r = self.http.post(
            self.env["PISTE_API_HOST"] + "/consult/getArticle",
            json={"id": article_id},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        if r.status_code == 401:
            self.login()
            raise Retryable("token expired")
        if r.status_code == 429 or r.status_code >= 500:
            raise Retryable(f"{r.status_code}")
        if r.status_code != 200:
            return {"error": f"{r.status_code} {r.text[:120]}"}
        art = r.json().get("article") or {}
        return {
            "id": art.get("id"),
            "cid": art.get("cid"),
            "num": art.get("num"),
            "etat": art.get("etat"),
            "dateFin": art.get("dateFin"),
            "versions": [
                {k: v.get(k) for k in ("id", "etat", "version", "dateDebut", "dateFin")}
                for v in art.get("articleVersions") or []
            ],
        }


def load_env() -> dict[str, str]:
    env = {}
    for line in ENV.read_text().splitlines():
        m = re.match(r"^(PISTE_\w+)=(.*)$", line.strip())
        if m:
            env[m[1]] = m[2].strip().strip("\"'")
    missing = [k for k in ("PISTE_API_HOST", "PISTE_TOKEN_HOST", "PISTE_OAUTH_CLIENT_ID",
                           "PISTE_OAUTH_CLIENT_SECRET") if not env.get(k)]
    if missing:
        sys.exit(f"missing in {ENV.resolve()}: {missing}")
    return env


def cited_ids() -> list[str]:
    html = EXPLORER.read_text()
    match = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    if match is None:
        sys.exit(f"no embedded data in {EXPLORER}")
    data = json.loads(match.group(1).replace("<\\/", "</"))
    return sorted({r["kali_id"] for r in data["rows"] if r.get("kali_id")})


def classify(info: dict) -> dict:
    if "error" in info:
        return {"status": "error", "detail": info["error"]}
    etat = info.get("etat") or ""
    if etat in IN_FORCE:
        return {"status": "current", "etat": etat}
    now_ms = time.time() * 1000
    later = [v for v in info["versions"]
             if (v.get("etat") or "") in IN_FORCE and (v.get("dateFin") or 0) >= min(now_ms, OPEN_END_MS)]
    if etat in {"REMPLACE", "MODIFIE", "MODIFIE_MORT_NE"} and later:
        cur = later[-1]
        return {"status": "replaced", "etat": etat, "current_id": cur["id"], "current_from": cur["dateDebut"],
                "versions": len(info["versions"])}
    if etat.startswith("ABROGE") or etat in {"PERIME", "ANNULE"}:
        return {"status": "abrogated", "etat": etat}
    return {"status": "other", "etat": etat, "versions": len(info["versions"])}


def main() -> None:
    env = load_env()
    ids = cited_ids()
    articles = [i for i in ids if i.startswith("KALIARTI")]
    print(f"{len(ids)} distinct cited ids, {len(articles)} KALIARTI to check "
          f"({len(ids) - len(articles)} are sections or texts, skipped)")
    cache: dict[str, dict] = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    client = Piste(env)
    client.login()
    todo = [i for i in articles if i not in cache or "error" in cache[i]]
    for n, i in enumerate(todo, 1):
        cache[i] = client.article(i)
        time.sleep(PAUSE)
        if n % 100 == 0:
            CACHE.write_text(json.dumps(cache))
            print(f"  {n}/{len(todo)}")
    CACHE.write_text(json.dumps(cache))

    results = {i: classify(cache[i]) for i in articles}
    counts = Counter(r["status"] for r in results.values())
    out = RUNS / f"link-versions-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)
    (out / "results.json").write_text(json.dumps(
        {"checked_at": datetime.now(UTC).isoformat(timespec="seconds"), "counts": counts, "articles": results},
        ensure_ascii=False, indent=1))
    print(dict(counts), "->", out / "results.json")


if __name__ == "__main__":
    main()
