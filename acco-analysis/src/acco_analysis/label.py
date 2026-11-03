"""Stage 4: name and describe each cluster from its passages (LLM), with verbatim
quotes that are checked against the passage text."""

import random
import re
import unicodedata
from typing import Any

import numpy as np

from acco_analysis.albert import Albert
from acco_analysis.cluster import nearest
from acco_analysis.relevance import excerpt

CENTRAL = 12  # passages closest to the centroid
OUTLYING = 4  # passages picked at random in the rest of the cluster, for the range
QUOTE_CHARS = 300

SYSTEM = """Tu es juriste en droit du travail français. Tu reçois un groupe d'extraits \
d'accords d'entreprise qui traitent de la chaleur (canicule, fortes chaleurs...) de façon \
voisine. Décris ce que ces extraits ont en commun et comment ils varient.

Réponds uniquement avec un objet JSON :
{
 "label": "<nom du type de clause, 8 mots max>",
 "summary": "<2 à 3 phrases : ce que prévoient ces clauses>",
 "variants": [{"name": "<variante, 6 mots max>", "description": "<1 phrase>"}],
 "triggers": ["<ce qui déclenche la mesure : vigilance, seuil de température...>"],
 "measures": ["<mesures prévues : horaires, pauses, eau, équipement, prime...>"],
 "quotes": [{"id": "<id de l'extrait>", "quote": "<citation copiée mot pour mot>"}]
}
Donne 2 à 5 variantes, et 3 citations de 300 caractères maximum, copiées exactement \
(sans reformuler, sans ajouter de « … ») depuis des extraits différents. "triggers" et \
"measures" peuvent être vides si les extraits n'en disent rien."""


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def clean_quote(quote: str) -> str:
    """The quote as it is compared: folded, without edge dots and quotation marks."""
    # NFKC writes "…" as "...": strip the dots too
    return _fold(quote).strip(" .…\"'«»")


def verbatim(quote: str, text: str) -> bool:
    """Is `quote` in `text`, up to case, spacing and accent encoding?"""
    q = clean_quote(quote)
    return len(q) >= 20 and q in _fold(text)


def pick(vectors: np.ndarray, members: np.ndarray, seed: int = 0) -> list[int]:
    close = nearest(vectors, members, CENTRAL)
    rest = [int(i) for i in members if int(i) not in set(close)]
    far = random.Random(seed).sample(rest, min(OUTLYING, len(rest)))
    return close + far


def label_cluster(
    albert: Albert, passages: list[dict[str, Any]], indices: list[int]
) -> dict[str, Any]:
    chosen = [passages[i] for i in indices]
    user = "\n\n".join(
        f"### [{p['id']}]\nTitre : {p['heading'] or '(sans titre)'}\n{excerpt(p['text'], 900)}"
        for p in chosen
    )
    answer = albert.chat_json(SYSTEM, user, max_tokens=3000)
    by_id = {p["id"]: p for p in chosen}
    quotes, dropped = [], 0
    for item in answer.get("quotes") or []:
        passage = by_id.get(item.get("id")) if isinstance(item, dict) else None
        quote = str(item.get("quote", "")) if isinstance(item, dict) else ""
        if passage and verbatim(quote, passage["text"]):
            quotes.append({"id": passage["id"], "quote": quote.strip()[:QUOTE_CHARS]})
        else:
            dropped += 1
    return {
        "label": str(answer.get("label", "")).strip(),
        "summary": str(answer.get("summary", "")).strip(),
        "variants": [v for v in answer.get("variants") or [] if isinstance(v, dict)],
        "triggers": [str(t) for t in answer.get("triggers") or []],
        "measures": [str(m) for m in answer.get("measures") or []],
        "quotes": quotes,
        "quotes_dropped": dropped,
        "shown": [p["id"] for p in chosen],
    }
