import httpx

from srdt_analysis.albert import AlbertBase
from srdt_analysis.constants import ALBERT_ENDPOINT, LLM_MODEL


class LLMProcessor(AlbertBase):
    SUMMARY_PROMPT = """
    Tu es un chatbot expert en droit du travail français. Lis le texte donné et rédige un résumé clair, précis et concis, 
    limité à 4096 tokens maximum. Dans ce résumé, fais ressortir les points clés suivants :
    
    Sujets principaux : identifie les droits et obligations des employeurs et des salariés, les conditions de travail, 
    les procédures, etc.
    
    Langage clair : simplifie le langage juridique tout en restant précis pour éviter toute confusion.
    
    Organisation logique : commence par les informations principales, puis détaille les exceptions ou points secondaires 
    s'ils existent.
    
    Neutralité : garde un ton factuel, sans jugement ou interprétation subjective.
    
    Longueur : si le texte est long, privilégie les informations essentielles pour respecter la limite de 4096 tokens.
    
    Ta réponse doit obligatoirement être en français.
    """

    KEYWORD_PROMPT = """
    Tu es un chatbot expert en droit du travail français. Ta seule mission est d'extraire une liste de mots-clés 
    à partir du texte fourni.
    
    Objectif : Les mots-clés doivent refléter les idées et thèmes principaux pour faciliter la compréhension et 
    la recherche du contenu du texte.
    
    Sélection : Extrait uniquement les termes essentiels, comme les droits et devoirs des employeurs et des salariés, 
    les conditions de travail, les procédures, les sanctions, etc.
    
    Non-redondance : Évite les répétitions ; chaque mot-clé doit apparaître une seule fois.
    
    Clarté et simplicité : Assure-toi que chaque mot-clé est compréhensible et pertinent.
    
    Format attendu pour la liste de mots-clés : une liste simple et directe, sans organisation par thèmes, comme dans 
    cet exemple : code du travail, article 12, congés payés, heures supplémentaires, licenciement économique.
    
    Ta réponse doit obligatoirement être en français.
    """

    QUESTION_PROMPT = """
    Tu es un chatbot expert en droit du travail français. Lis attentivement le texte fourni et génère une liste de questions pertinentes et variées, limitées à 4096 tokens. Ces questions doivent permettre d'approfondir la compréhension du contenu et de guider une analyse ou une discussion sur le sujet.

    Directives pour la génération des questions :

    Représentation des idées principales : Formule des questions en lien avec les droits et devoirs des employeurs et des salariés, les conditions de travail, les procédures légales, les sanctions, etc.
    Variété : Génère des questions ouvertes (ex. : "Quels sont les droits d'un salarié en cas de licenciement économique ?") et fermées (ex. : "Un employeur peut-il refuser une demande de congés payés ?").
    Clarté : Les questions doivent être claires, concises et directement liées au texte fourni, sans ambiguïté.
    Priorité au contenu essentiel : Donne la priorité aux informations clés du texte, mais inclue également des questions sur des points secondaires si pertinent.
    Neutralité : Rédige des questions neutres, sans parti pris ou interprétation subjective.
    Respect de la longueur : Si le texte est très long, concentre-toi sur les parties les plus importantes pour générer des questions dans la limite de 4096 tokens.
    Format attendu pour les questions : Une liste numérotée ou à puces, claire et ordonnée. Exemple :

    Quels sont les critères de validité d'un contrat de travail ?
    Quelles sont les obligations légales d'un employeur en cas de licenciement ?
    Comment sont calculées les heures supplémentaires selon le Code du travail ?
    Ta réponse doit obligatoirement être en français. 
    """

    def _make_request(self, message: str, system_prompt: str) -> str:
        # TODO
        return ""
        try:
            response = httpx.post(
                f"{ALBERT_ENDPOINT}/v1/chat/completions",
                headers=self.headers,
                json={
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    "model": LLM_MODEL,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Request failed: {e.response.status_code} - {e.response.text}"
            ) from e
        except Exception as e:
            raise RuntimeError(f"An error occurred: {str(e)}") from e

    def get_summary(self, message: str) -> str:
        """Génère un résumé du texte fourni."""
        return self._make_request(message, self.SUMMARY_PROMPT)

    def get_keywords(self, message: str) -> str:
        """Extrait les mots-clés du texte fourni."""
        return self._make_request(message, self.KEYWORD_PROMPT)

    def get_questions(self, message: str) -> str:
        """Génère des questions à partir du texte fourni."""
        return self._make_request(message, self.QUESTION_PROMPT)
