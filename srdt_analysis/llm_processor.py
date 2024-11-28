import asyncio
import logging
from functools import lru_cache
from typing import Any, Dict, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from srdt_analysis.albert import AlbertBase
from srdt_analysis.constants import ALBERT_ENDPOINT, LLM_MODEL
from srdt_analysis.models import ChunkDataListWithDocument

logger = logging.getLogger(__name__)


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

    LLM_PROMPT = """
    Vous êtes un assistant juridique spécialisé en droit du travail. Votre rôle est de répondre à la question posée par l'utilisateur en vous basant uniquement sur les informations présentes dans les documents suivants : [DOCUMENTS]. Ne faites aucune supposition ni inférence en dehors des contenus de ces documents. Si la réponse ne peut pas être déduite ou trouvée directement dans ces documents, indiquez clairement que l'information n'est pas disponible.

    Consignes spécifiques :
    Si plusieurs documents contiennent des informations contradictoires, signalez cette contradiction.
    Mentionnez précisément les passages ou les extraits des documents utilisés pour répondre.
    Si une explication juridique est nécessaire, elle doit être entièrement fondée sur le contenu des documents fournis.
    Si l'utilisateur pose une question dont la réponse n'est pas trouvée dans les documents, répondez : "Les documents fournis ne contiennent pas l'information demandée."
    """

    def __init__(self):
        super().__init__()
        self.client = httpx.AsyncClient()
        self.rate_limit = asyncio.Semaphore(10)

    def __del__(self):
        asyncio.create_task(self.client.aclose())

    def _validate_response(self, response: Dict[str, Any]) -> str:
        """Validate and extract content from LLM response"""
        if not response.get("choices"):
            raise ValueError("Invalid response format: no choices found")
        content = response["choices"][0]["message"]["content"]
        if not content:
            raise ValueError("Empty response content")
        return content

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def _make_request_async(
        self,
        message: str,
        system_prompt: str,
        conversation_history: Optional[list] = None,
    ) -> str:
        """Async version of make request with retry logic"""
        async with self.rate_limit:
            try:
                messages = [{"role": "system", "content": system_prompt}]

                if conversation_history:
                    messages.extend(conversation_history)

                messages.append({"role": "user", "content": message})

                response = await self.client.post(
                    f"{ALBERT_ENDPOINT}/v1/chat/completions",
                    headers=self.headers,
                    json={
                        "messages": messages,
                        "model": LLM_MODEL,
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                return self._validate_response(response.json())
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
                )
                raise
            except Exception as e:
                logger.error(f"Error making request: {str(e)}")
                raise

    @lru_cache(maxsize=100)
    async def get_summary_async(self, message: str) -> str:
        """Async version of get_summary with caching"""
        logger.info("Generating summary for text")
        return await self._make_request_async(message, self.SUMMARY_PROMPT)

    @lru_cache(maxsize=100)
    async def get_keywords_async(self, message: str) -> str:
        """Async version of get_keywords with caching"""
        logger.info("Extracting keywords from text")
        return await self._make_request_async(message, self.KEYWORD_PROMPT)

    @lru_cache(maxsize=100)
    async def get_questions_async(self, message: str) -> str:
        """Async version of get_questions with caching"""
        logger.info("Generating questions from text")
        return await self._make_request_async(message, self.QUESTION_PROMPT)

    async def get_answer_async(
        self,
        message: str,
        documents: ChunkDataListWithDocument,
        conversation_history: Optional[list] = None,
    ) -> str:
        """Async version of get_answer"""
        logger.info("Generating answer based on documents")
        document_contents = [item["content"] for item in documents["data"]]
        system_prompt = self.LLM_PROMPT.replace(
            "[DOCUMENTS]", "\n".join(document_contents)
        )
        return await self._make_request_async(
            message, system_prompt, conversation_history
        )

    def get_summary(self, message: str) -> str:
        return asyncio.run(self.get_summary_async(message))

    def get_keywords(self, message: str) -> str:
        return asyncio.run(self.get_keywords_async(message))

    def get_questions(self, message: str) -> str:
        return asyncio.run(self.get_questions_async(message))

    def get_answer(
        self,
        message: str,
        documents: ChunkDataListWithDocument,
        conversation_history: Optional[list] = None,
    ) -> str:
        return asyncio.run(
            self.get_answer_async(message, documents, conversation_history)
        )
