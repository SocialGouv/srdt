"""
Évaluation de la précision des jurisprudences citées par l'assistant.

Pour chaque question du dataset, le script appelle l'API /api/generate et
extrait les liens courdecassation.fr/decision/<id> présents dans la réponse
finale (texte généré).

Précision d'une question =
    nb de liens cités qui correspondent à un lien attendu du dataset
    / nb total de liens courdecassation cités dans la réponse
(None si la réponse ne cite aucune jurisprudence).

La précision globale est calculée en micro-moyenne (somme des liens corrects /
somme des liens cités sur toutes les questions).

Le résultat de chaque question est ajouté (sans écraser les précédents) dans
la liste "results" de l'entrée correspondante du dataset, avec la date du test,
l'environnement utilisé et les temps de traitement. Avec --replace, les
résultats précédents portant le même libellé --env sont remplacés.

Temps enregistrés (en secondes) :
- response_time_s : durée de l'appel HTTP vue par le client ;
- server_total_time_s : durée totale du traitement côté serveur (debug.totalTime) ;
- generation_time_s : durée de la génération de la réponse par le LLM ;
- preparation_time_s : server_total_time_s - generation_time_s, c.-à-d. le temps
  passé avant la génération (anonymisation, recherches, rerank, filtre LLM des
  jurisprudences...).
Pour des temps comparables, lancer avec --workers 1 (appels séquentiels).

Usage :
    export SRDT_API_TOKEN=<token debug>   # sans le "$" devant
    python3 test/eval_jurisprudences.py [--env production] [--url ...] [--dataset ...]
                                        [--workers 1] [--replace]
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_DATASET = os.path.join(
    os.path.dirname(__file__), "..", "dataset", "dataset_jurisprudences.json"
)
DEFAULT_URL = "https://web-srdt.fabrique.social.gouv.fr/api/generate"

# Identifiant d'une décision Judilibre dans une URL courdecassation.fr.
# On compare les identifiants (et non les URLs complètes) pour ignorer les
# paramètres de recherche parfois présents dans les URLs du dataset.
DECISION_ID = re.compile(r"courdecassation\.fr/decision/([0-9a-f]{24})")


def decision_url(decision_id):
    return f"https://www.courdecassation.fr/decision/{decision_id}"


def call_api(url, token, question, retries=3):
    """Appelle /api/generate et renvoie (data, durée de l'appel réussi en s).

    Le token debug permet de contourner l'authentification par session.
    La génération peut prendre plusieurs dizaines de secondes, d'où le
    timeout élevé et les quelques tentatives en cas d'erreur.
    """
    error = None
    for _ in range(retries):
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps({"question": question}).encode(),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            start = time.monotonic()
            with urllib.request.urlopen(request, timeout=400) as response:
                body = json.load(response)
            if body.get("success"):
                return body["data"], time.monotonic() - start
            error = body.get("error")
        except Exception as e:  # erreur réseau, 401, 500...
            error = str(e)
    raise RuntimeError(f"Échec de l'appel pour « {question} » : {error}")


def evaluate(item, data, test_date, env, response_time=None):
    """Calcule le résultat d'une question à partir de la réponse de l'API."""
    answer = data["generated"]["text"]
    generation_time = data["generated"].get("time")
    # debug.totalTime n'est renvoyé qu'avec le token debug
    server_total_time = (data.get("debug") or {}).get("totalTime")

    # Jurisprudences remontées par la recherche (contexte fourni au LLM).
    retrieved = {
        chunk["metadata"]["url"]: chunk["metadata"].get("number")
        for chunk in data["localSearchChunks"]
        if chunk["metadata"].get("source") == "judilibre"
    }

    # Jurisprudences citées dans la réponse finale : par lien direct, ou par
    # numéro de pourvoi (ex. "21-15.189") d'une décision du contexte.
    cited_ids = set(DECISION_ID.findall(answer))
    for url, number in retrieved.items():
        if number and number in answer:
            cited_ids.add(DECISION_ID.search(url).group(1))

    expected_ids = {
        m.group(1)
        for url in item["expected_sources"]
        for m in [DECISION_ID.search(url)]
        if m
    }
    retrieved_ids = {DECISION_ID.search(url).group(1) for url in retrieved}

    cited = sorted(decision_url(i) for i in cited_ids)
    matching = sorted(decision_url(i) for i in cited_ids & expected_ids)

    return {
        "date": test_date,
        "environment": env,
        "response_time_s": round(response_time, 2) if response_time else None,
        "server_total_time_s": round(server_total_time, 2)
        if server_total_time
        else None,
        "generation_time_s": round(generation_time, 2) if generation_time else None,
        "preparation_time_s": round(server_total_time - generation_time, 2)
        if server_total_time and generation_time
        else None,
        # Métrique principale : part des liens cités qui sont attendus.
        "precision": round(len(matching) / len(cited), 3) if cited else None,
        "cited_matching_expected": matching,
        "cited_not_matching_expected": [u for u in cited if u not in matching],
        # Complément : part des liens attendus présents dans la réponse.
        "recall": round(len(cited_ids & expected_ids) / len(expected_ids), 3)
        if expected_ids
        else None,
        "expected_missing_from_answer": sorted(
            decision_url(i) for i in expected_ids - cited_ids
        ),
        "jurisprudences_cited_in_answer": cited,
        # Permet de savoir si un lien manquant vient de la recherche
        # (jamais récupéré) ou de la génération (récupéré mais non cité).
        "expected_retrieved_in_context": sorted(
            decision_url(i) for i in expected_ids & retrieved_ids
        ),
        "jurisprudences_retrieved_in_context": sorted(retrieved),
        "answer": answer,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--env",
        default="production",
        help="Libellé de l'environnement enregistré avec les résultats",
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="Nombre d'appels en parallèle"
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Remplace les résultats existants ayant le même libellé --env",
    )
    args = parser.parse_args()

    token = os.environ.get("SRDT_API_TOKEN")
    if not token:
        sys.exit("Variable d'environnement SRDT_API_TOKEN manquante.")

    with open(args.dataset, encoding="utf-8") as f:
        dataset = json.load(f)

    test_date = datetime.date.today().isoformat()

    def run(item):
        data, response_time = call_api(args.url, token, item["question"])
        return evaluate(item, data, test_date, args.env, response_time)

    with ThreadPoolExecutor(args.workers) as executor:
        results = list(executor.map(run, dataset))

    # On ajoute le résultat à l'historique de chaque question.
    for item, result in zip(dataset, results):
        previous = item.setdefault("results", [])
        if args.replace:
            previous[:] = [r for r in previous if r["environment"] != args.env]
        previous.append(result)

    with open(args.dataset, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # Récapitulatif console.
    total_matching = total_cited = 0
    print(f"{'Q':>3}  {'corrects/cités':>14}  précision  préparation  génération  total")
    for item, result in zip(dataset, results):
        n_match = len(result["cited_matching_expected"])
        n_cited = len(result["jurisprudences_cited_in_answer"])
        total_matching += n_match
        total_cited += n_cited
        precision = (
            f"{result['precision']:.0%}" if result["precision"] is not None else "n/a"
        )
        print(
            f"{item['id']:>3}  {f'{n_match}/{n_cited}':>14}  {precision:>9}"
            f"  {result['preparation_time_s'] or '-':>10}s"
            f"  {result['generation_time_s'] or '-':>9}s"
            f"  {result['response_time_s'] or '-':>5}s"
        )
    times = [r["preparation_time_s"] for r in results if r["preparation_time_s"]]
    if times:
        print(f"Temps de préparation moyen : {sum(times) / len(times):.1f}s")
    times = [r["response_time_s"] for r in results if r["response_time_s"]]
    if times:
        print(f"Temps de réponse moyen : {sum(times) / len(times):.1f}s")
    if total_cited:
        print(
            f"Précision globale ({args.env}, {test_date}) : "
            f"{total_matching}/{total_cited} = {total_matching / total_cited:.1%}"
        )


if __name__ == "__main__":
    main()
