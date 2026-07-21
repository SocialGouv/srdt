"""
Client pour l'API Judilibre - recuperation des decisions de la Cour de cassation.

Filtre les decisions publiees au bulletin et relevant de la chambre sociale
(droit social), sur une plage de dates donnee.
"""

import os
import time
from typing import Dict, List

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from srdt_analysis.core.constants import JUDILIBRE_BASE_URL

# Filtres de recherche Judilibre
jurisdiction: str = "cc"  # Cour de cassation
publication: str = "b"  # publiees au bulletin
chamber: str = "soc"  # chambre sociale (droit social)


def get_decision_url(decision_id: str) -> str:
    """Construit l'URL publique d'une decision."""
    return f"https://www.courdecassation.fr/decision/{decision_id}"


class JudilibreClient:
    """Client pour interroger l'API Judilibre."""

    def __init__(self):
        self.base_url = JUDILIBRE_BASE_URL
        self.batch_size = 50
        self.headers = {
            "accept": "application/json",
            "KeyId": os.getenv("JUDILIBRE_API_KEY"),
        }

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    def get_decisions_between_dates(self, date_start: str, date_end: str) -> List[Dict]:
        """
        Recupere les decisions CC bulletin / chambre sociale entre deux dates.

        Args:
            date_start: Date de debut (incluse), format YYYY-MM-DD
            date_end: Date de fin (incluse), format YYYY-MM-DD

        Returns:
            Liste de decisions avec leurs metadonnees
        """

        all_decisions: List[Dict] = []
        page = 0  # l'API Judilibre est 0-indexee : la premiere page est page=0
        page_size = self.batch_size

        params = {
            "query": "*",
            "jurisdiction": jurisdiction,
            "chamber": chamber,
            "publication": publication,
            "date_start": date_start,
            "date_end": date_end,
            "page_size": page_size,
        }

        while True:
            params["page"] = page
            response = requests.get(
                f"{self.base_url}/search",
                headers=self.headers,
                params=params,
                timeout=30,
            )

            # 416 = depassement de la fenetre de pagination autorisee par l'API
            if response.status_code == 416:
                break

            response.raise_for_status()
            data = response.json()

            decisions = data.get("results", [])
            if not decisions:
                break

            for d in decisions:
                all_decisions.append(
                    {
                        "id": d.get("id"),
                        "number": d.get("number"),
                        "decision_date": d.get("decision_date"),
                        "chamber": d.get("chamber"),
                        "formation": d.get("formation"),
                        "type": d.get("type"),
                        "solution": d.get("solution"),
                        "publication": d.get("publication"),
                        "titlesAndSummaries": d.get("titlesAndSummaries"),
                    }
                )

            if len(decisions) < page_size:
                break

            page += 1
            time.sleep(1.0)

        return all_decisions

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    def get_decision_full_text(self, decision_id: str) -> str:
        """Recupere le texte complet d'une decision via son ID."""
        response = requests.get(
            f"{self.base_url}/decision",
            headers=self.headers,
            params={"id": decision_id},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("text", "")
