"""Stage 4b: group the cluster labels into families of clauses (LLM).

k-means over-segments a continuum: several clusters describe the same kind of clause
(three "protective measures" groups, three telework groups). One LLM call reads the
cluster labels, summaries, triggers and measures and groups the clusters that say the
same thing. The grouping is checked here: every cluster lands in exactly one family.
"""

from typing import Any

from acco_analysis.albert import Albert

MIN_FAMILIES = 4
MAX_FAMILIES = 8

SYSTEM = f"""Tu es juriste en droit du travail français. Tu reçois les descriptions de \
groupes de clauses d'accords d'entreprise sur la chaleur (canicule, fortes chaleurs...). \
Un algorithme de regroupement a découpé un ensemble continu en trop de groupes : \
plusieurs décrivent la même chose avec des mots différents.

Regroupe les groupes qui décrivent le même type de clause en {MIN_FAMILIES} à \
{MAX_FAMILIES} familles. Règles :
- une famille réunit des groupes dont la mesure et le mécanisme sont les mêmes \
(par exemple plusieurs groupes sur le télétravail déclenché par la canicule) ;
- ne fusionne pas deux groupes qui prévoient des mesures différentes parce qu'ils \
partagent un mot ; un groupe qui ne ressemble à aucun autre forme une famille à lui seul ;
- chaque groupe appartient à une et une seule famille ; n'invente aucun numéro.

Réponds uniquement avec un objet JSON, dont les clés s'écrivent exactement \
"families", "label", "summary" et "clusters" (en anglais, même si le texte est en français) :
{{"families": [{{"label": "<nom de la famille, 8 mots max>", "summary": "<2 phrases : \
ce que prévoient ces clauses et ce qui distingue les groupes réunis>", \
"clusters": [<numéros des groupes>]}}]}}"""


def _describe(cluster: dict[str, Any]) -> str:
    parts = [
        f"### Groupe {cluster['cluster']}: {cluster['label']}",
        f"{cluster['agreements']} accords, {cluster['specific']} extraits spécifiques, "
        f"{cluster['generic']} génériques",
        cluster["summary"],
    ]
    if cluster.get("triggers"):
        parts.append("Déclencheurs : " + "; ".join(cluster["triggers"]))
    if cluster.get("measures"):
        parts.append("Mesures : " + "; ".join(cluster["measures"]))
    return "\n".join(parts)


def check(answer: Any, cluster_ids: set[int]) -> tuple[list[dict[str, Any]], list[str]]:
    """(families, problems). A family keeps only valid, unused cluster ids."""
    raw = answer.get("families") if isinstance(answer, dict) else None
    problems: list[str] = []
    if not isinstance(raw, list) or not raw:
        return [], ['la réponse n\'a pas de liste "families"']
    seen: set[int] = set()
    families: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            problems.append("une famille n'est pas un objet")
            continue
        members: list[int] = []
        for value in item.get("clusters") or []:
            if not isinstance(value, int) or isinstance(value, bool):
                problems.append(f"numéro de groupe invalide : {value!r}")
            elif value not in cluster_ids:
                problems.append(f"le groupe {value} n'existe pas")
            elif value in seen:
                problems.append(f"le groupe {value} est dans plusieurs familles")
            else:
                seen.add(value)
                members.append(value)
        if members:
            families.append(
                {
                    "label": str(item.get("label", "")).strip(),
                    "summary": str(item.get("summary", "")).strip(),
                    "clusters": sorted(members),
                }
            )
    missing = sorted(cluster_ids - seen)
    if missing:
        problems.append(f"groupes sans famille : {missing}")
    if not MIN_FAMILIES <= len(families) <= MAX_FAMILIES:
        problems.append(
            f"{len(families)} familles, il en faut de {MIN_FAMILIES} à {MAX_FAMILIES}"
        )
    return families, problems


def merge_clusters(albert: Albert, clusters: list[dict[str, Any]]) -> dict[str, Any]:
    """The families of `clusters` (dicts of the report: cluster, label, summary...).

    Asked a second time, with the problems listed, when the grouping is not valid.
    What is still wrong after that is repaired rather than dropped: a cluster left
    out becomes a family of its own, and the result says so."""
    ids = {c["cluster"] for c in clusters}
    user = "\n\n".join(_describe(c) for c in clusters)
    families, problems = check(albert.chat_json(SYSTEM, user), ids)
    retried = bool(problems)
    if problems:
        feedback = (
            f"{user}\n\nTa réponse précédente était invalide : {'; '.join(problems)}. "
            'Corrige-la, avec exactement les clés "families", "label", "summary" et '
            '"clusters".'
        )
        families, problems = check(albert.chat_json(SYSTEM, feedback), ids)

    placed = {i for f in families for i in f["clusters"]}
    by_id = {c["cluster"]: c for c in clusters}
    for i in sorted(ids - placed):
        families.append(
            {
                "label": by_id[i]["label"],
                "summary": by_id[i]["summary"],
                "clusters": [i],
            }
        )
    families.sort(key=lambda f: -sum(by_id[i]["passages"] for i in f["clusters"]))
    return {"families": families, "retried": retried, "unresolved": problems}
