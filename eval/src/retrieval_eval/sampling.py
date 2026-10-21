"""Representative sample of real user questions (no I/O, no anonymisation).

Strata are length buckets, which drive retrieval behaviour (a three-word keyword
query and a ten-line scenario do not behave alike). Inside a bucket we balance
themes and cap how many questions one user can contribute. Everything is seeded.
"""

import hashlib
import random
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

BUCKETS = ("keyword", "short", "detailed")
KEYWORD_MAX = 40  # characters, exclusive
SHORT_MAX = 250

MIN_LENGTH = 10
MAX_LENGTH = 2000  # a longer text is cut by nobody: it would change the intent
DROPPED_DEPARTMENTS = ("Fabrique Numérique", "Beta.gouv")
GOLDEN_SIMILARITY = 0.8

# Matched on lower-cased, accent-free text. The first match wins, so the more
# specific themes come first. A reporting and balancing aid, not ground truth.
THEMES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern))
    for name, pattern in (
        ("rupture_conventionnelle", r"rupture conv|rupture amiable"),
        ("licenciement", r"licenci|inaptitude|faute (grave|lourde)|plan social"),
        ("demission", r"demission|demissionn|abandon de poste"),
        ("periode_essai", r"periode d.essai"),
        ("preavis", r"preavis"),
        ("harcelement_discipline", r"harcel|sanction|disciplin|avertissement"),
        (
            "maladie_accident",
            r"maladie|accident du travail|invalidite|arret de travail",
        ),
        (
            "conges",
            r"conges?\b|\bcp\b|\brtt\b|vacances|jours? feries?|maternite|paternite",
        ),
        ("contrat_precaire", r"\bcdd\b|interim|contrat a duree determinee|saisonnier"),
        (
            "duree_travail",
            r"heures? sup|temps partiel|horaire|duree du travail|forfait|astreinte"
            r"|repos|nuit|dimanche",
        ),
        (
            "salaire_primes",
            r"salaire|prime|remuneration|paie|indemnit|13e|treizieme|smic|coefficient",
        ),
        ("retraite", r"retraite"),
        ("teletravail", r"teletravail"),
        ("mutation_modification", r"mutation|mobilite|modification du contrat|avenant"),
        ("representation", r"\bcse\b|syndic|delegue|election"),
        ("formation", r"formation|apprenti|alternance|\bcpf\b"),
    )
)
OTHER_THEME = "autre"


@dataclass(frozen=True)
class Candidate:
    text: str
    user: str
    idcc: str | None
    bucket: str
    theme: str


def normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def clean_question(raw: str) -> str:
    """Whitespace trimmed, and the literal quotes some exports wrap the text in."""
    text = raw.strip()
    while len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    return text


def length_bucket(text: str) -> str:
    if len(text) < KEYWORD_MAX:
        return "keyword"
    return "short" if len(text) < SHORT_MAX else "detailed"


def theme_of(text: str) -> str:
    plain = _strip_accents(text.lower())
    return next((name for name, rx in THEMES if rx.search(plain)), OTHER_THEME)


def query_id(text: str) -> str:
    return "q_" + hashlib.sha1(normalise(text).encode()).hexdigest()[:8]


def is_near_golden(text: str, golden: list[str]) -> bool:
    mine = normalise(text)
    return any(
        SequenceMatcher(None, mine, normalise(g)).ratio() > GOLDEN_SIMILARITY
        for g in golden
    )


def build_candidates(
    rows: list[dict[str, str]], golden: list[str]
) -> tuple[list[Candidate], Counter[str]]:
    """Filter and dedupe export rows (columns Question, User ID, Department, Idcc)."""
    dropped: Counter[str] = Counter()
    seen: set[str] = set()
    candidates: list[Candidate] = []
    for row in rows:
        text = clean_question(row["Question"])
        if row["Department"] in DROPPED_DEPARTMENTS:
            dropped["test_department"] += 1
        elif len(text) < MIN_LENGTH:
            dropped["too_short"] += 1
        elif len(text) > MAX_LENGTH:
            dropped["too_long"] += 1
        elif normalise(text) in seen:
            dropped["duplicate"] += 1
        elif is_near_golden(text, golden):
            dropped["near_golden"] += 1
        else:
            seen.add(normalise(text))
            candidates.append(
                Candidate(
                    text=text,
                    user=row["User ID"],
                    idcc=row["Idcc"].strip() or None,
                    bucket=length_bucket(text),
                    theme=theme_of(text),
                )
            )
    return candidates, dropped


def allocate(counts: dict[str, int], n: int, floor: int) -> dict[str, int]:
    """Proportional quotas (largest remainder), at least `floor` per stratum."""
    if n > sum(counts.values()):
        raise ValueError(f"cannot sample {n} from {sum(counts.values())} candidates")
    floors = {k: min(floor, c) for k, c in counts.items()}
    if sum(floors.values()) > n:
        raise ValueError(f"n={n} is below the sum of floors {floors}")
    total = sum(counts.values())
    exact = {k: n * c / total for k, c in counts.items()}
    quota = {k: max(floors[k], int(exact[k])) for k in counts}
    # Fix the total: hand out or take back units by remainder, never under the floor.
    while sum(quota.values()) < n:
        k = max(
            (k for k in counts if quota[k] < counts[k]),
            key=lambda k: (exact[k] - quota[k], k),
        )
        quota[k] += 1
    while sum(quota.values()) > n:
        k = min(
            (k for k in counts if quota[k] > floors[k]),
            key=lambda k: (exact[k] - quota[k], k),
        )
        quota[k] -= 1
    return quota


def _pick_in_stratum(
    pool: list[Candidate],
    quota: int,
    users: Counter[str],
    user_cap: int,
    rng: random.Random,
) -> list[Candidate]:
    """Take `quota` candidates, always from the theme furthest below its share."""
    by_theme: dict[str, list[Candidate]] = defaultdict(list)
    for c in pool:
        by_theme[c.theme].append(c)
    for theme in by_theme:
        rng.shuffle(by_theme[theme])
    target = {t: quota * len(cs) / len(pool) for t, cs in by_theme.items()}
    taken: Counter[str] = Counter()

    picked: list[Candidate] = []
    while len(picked) < quota:
        for theme in sorted(by_theme, key=lambda t: (taken[t] - target[t], t)):
            queue = by_theme[theme]
            while queue and users[queue[-1].user] >= user_cap:
                queue.pop()
            if queue:
                chosen = queue.pop()
                users[chosen.user] += 1
                taken[theme] += 1
                picked.append(chosen)
                break
        else:
            raise ValueError(
                f"stratum exhausted after {len(picked)}/{quota} picks "
                f"(user cap {user_cap}): lower n or raise the cap"
            )
    return picked


def select(
    candidates: list[Candidate],
    n: int,
    seed: int,
    user_cap: int = 3,
    floor: int = 15,
) -> list[Candidate]:
    rng = random.Random(seed)
    strata = {b: [c for c in candidates if c.bucket == b] for b in BUCKETS}
    quotas = allocate({b: len(cs) for b, cs in strata.items() if cs}, n, floor)
    users: Counter[str] = Counter()
    picked: list[Candidate] = []
    for bucket in BUCKETS:
        if bucket in quotas:
            pool = sorted(strata[bucket], key=lambda c: normalise(c.text))
            picked += _pick_in_stratum(pool, quotas[bucket], users, user_cap, rng)
    return picked


def assign_splits(
    bucket_of: dict[str, str], seed: int, dev_size: int
) -> dict[str, str]:
    """dev/test per query id: `dev_size` queries in dev, spread over the buckets.

    The dev set exists to tune the labeller prompt without touching the reported
    numbers, so it is small. Each bucket gets its proportional share of it.
    """
    rng = random.Random(seed)
    counts = Counter(bucket_of.values())
    dev_size = min(dev_size, len(bucket_of))
    quota = allocate(dict(counts), dev_size, floor=0)
    splits: dict[str, str] = {}
    for bucket in BUCKETS:
        ids = sorted(q for q, b in bucket_of.items() if b == bucket)
        rng.shuffle(ids)
        for position, q in enumerate(ids):
            splits[q] = "dev" if position < quota.get(bucket, 0) else "test"
    return splits


_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("digits", re.compile(r"\d[\d .-]{4,}\d")),
    ("at_sign", re.compile(r"@")),
    ("url", re.compile(r"https?://|www\.", re.I)),
    (
        "title_name",
        re.compile(r"\b(?:Madame|Monsieur|Mme|Mlle|M\.|Mr)\s+[A-ZÉÈÀ][\w'-]+"),
    ),
    ("self_intro", re.compile(r"je m.appelle|mon nom est|\bné(?:e)? le\b", re.I)),
)


def pii_flags(text: str) -> list[str]:
    """Cheap heuristics for what the anonymiser may have missed. Review by hand."""
    return [name for name, rx in _PII_PATTERNS if rx.search(text)]
