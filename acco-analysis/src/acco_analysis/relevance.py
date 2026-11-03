"""Stage 2: is the passage a heat clause, or a passing mention?

Three labels, set by an LLM from the passage and its heading:
- specific: a measure, right, procedure or action that is about heat;
- generic: heat is one of several events or risks that trigger a general measure
  ("neige, canicule, etc." in a clause on exceptional telework or absence);
- mention: no measure about heat (reminder, context, definition, footnote, heat in
  another sense).
"""

import re
from collections.abc import Sequence
from typing import Any

from acco_analysis.albert import Albert, run_concurrently
from acco_analysis.extract import PHRASE_RE, VARIANT_RE

LABELS = ("specific", "generic", "mention")
KEPT = ("specific", "generic")
BATCH = 6
WORKERS = 4
EXCERPT_CHARS = 1500

SYSTEM = """Tu es juriste en droit du travail français. Tu reçois des extraits d'accords \
d'entreprise qui contiennent un terme lié à la chaleur (canicule, fortes chaleurs, \
températures extrêmes...). Pour chaque extrait, indique le rôle de la chaleur dans le texte. \
Ce qui compte est ce que le texte FAIT à propos de la chaleur : il prévoit une mesure, ou il \
ne fait que la nommer.

- "specific" : l'extrait fixe une mesure, un droit, une procédure, un seuil ou une action \
qui concerne précisément la chaleur (horaires aménagés, pauses, distribution d'eau, \
équipements, seuil de température, déclenchement par un niveau de vigilance, prime, plan \
d'action...). Le préambule, l'objet ou le titre d'un accord entièrement consacré à la \
canicule ou aux fortes chaleurs est aussi "specific".
- "generic" : la chaleur est l'un des événements d'une liste (intempéries, neige, \
inondation, pollution, canicule...) qui déclenche une mesure que le texte décrit \
(télétravail exceptionnel, autorisation de quitter le poste, retard ou absence justifiés, \
aménagement des horaires et prime qui en découle...), même introduite par "notamment" ou \
"par exemple".
- "mention" : le texte nomme la chaleur sans prévoir de mesure à son sujet :
  - ordre du jour, thèmes à négocier ou à discuter, calendrier de réunions, revendications \
ou demandes syndicales, sommaire, table des matières ;
  - indicateurs de suivi ; liste de risques ou de facteurs de pénibilité (par exemple les \
facteurs du compte professionnel de prévention : bruit, températures extrêmes, travail de \
nuit...) ;
  - simple rappel, contexte ou objectif, définition, note de bas de page ;
  - "chaleur" dans un autre sens (source de chaleur, chauffage).

En cas de doute entre "specific" ou "generic" et "mention", choisis "mention" si l'extrait \
ne dit pas ce qui est fait en cas de chaleur. Un extrait qui mêle une simple liste et une \
vraie clause prend le libellé de la clause.
Réponds uniquement avec un objet JSON : \
{"results": [{"id": "<id>", "label": "specific|generic|mention", "reason": "<15 mots max>"}]}"""


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """At most `limit` characters, around the first heat term."""
    if len(text) <= limit:
        return text
    m = PHRASE_RE.search(text) or VARIANT_RE.search(text)
    centre = m.start() if m else 0
    start = max(0, min(centre - limit // 3, len(text) - limit))
    return ("…" if start else "") + text[start : start + limit] + "…"


def _prompt(batch: Sequence[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"### [{p['id']}]\nTitre : {p['heading'] or '(sans titre)'}\n{excerpt(p['text'])}"
        for p in batch
    )


def _parse(answer: Any, ids: set[str]) -> dict[str, dict[str, str]]:
    results = answer.get("results") if isinstance(answer, dict) else None
    parsed: dict[str, dict[str, str]] = {}
    for item in results or []:
        if (
            isinstance(item, dict)
            and item.get("id") in ids
            and item.get("label") in LABELS
        ):
            parsed[item["id"]] = {
                "label": item["label"],
                "reason": str(item.get("reason", ""))[:200],
            }
    return parsed


def classify(
    albert: Albert, passages: Sequence[dict[str, Any]], batch: int = BATCH
) -> dict[str, dict[str, str]]:
    """{passage id: {"label", "reason"}}. A passage the model skipped or mislabelled is
    asked again alone."""
    batches = [passages[i : i + batch] for i in range(0, len(passages), batch)]

    def run(group: Sequence[dict[str, Any]]) -> dict[str, dict[str, str]]:
        ids = {p["id"] for p in group}
        return _parse(albert.chat_json(SYSTEM, _prompt(group)), ids)

    labelled: dict[str, dict[str, str]] = {}
    for part in run_concurrently(run, batches, WORKERS):
        labelled.update(part)
    for p in passages:
        if p["id"] not in labelled:
            labelled.update(run([p]))
    missing = [p["id"] for p in passages if p["id"] not in labelled]
    if missing:
        raise RuntimeError(f"{len(missing)} passages unlabelled, e.g. {missing[0]}")
    return labelled


def is_heat_text(text: str) -> bool:
    return bool(re.search(PHRASE_RE, text) or re.search(VARIANT_RE, text))
