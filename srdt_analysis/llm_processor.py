import asyncio
import json
import logging
import warnings
from functools import lru_cache
from types import TracebackType
from typing import Any, AsyncGenerator, Dict, Iterator, List, Optional, Type

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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
    Voici les documents suivants : [DOCUMENTS]
    
    Peux tu reformuler une réponse en se basant sur ces documents ?
    
    La réponse doit faire au moins 10 lignes.
    """

    def __init__(self):
        super().__init__()
        self._client = None
        self.rate_limit = asyncio.Semaphore(10)

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def __aenter__(self) -> "LLMProcessor":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the HTTP client properly"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def __del__(self):
        if self._client is not None:
            warnings.warn(
                "LLMProcessor was not properly closed. Please use 'async with' or call 'await close()'"
            )

    def _validate_response(self, response: Dict[str, Any]) -> str:
        try:
            if not response.get("choices"):
                raise ValueError("Invalid response format: no choices found")
            content = response["choices"][0]["message"]["content"]
            if not content:
                raise ValueError("Empty response content")
            return content
        except (KeyError, IndexError) as e:
            raise ValueError(f"Invalid response structure: {str(e)}") from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, ValueError)),
    )
    async def _make_request_stream_async(
        self,
        message: str,
        system_prompt: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[str, None]:
        async with self.rate_limit:
            try:
                messages = [{"role": "system", "content": system_prompt}]
                if conversation_history:
                    messages.extend(conversation_history)
                messages.append({"role": "user", "content": message})

                async with self.client.stream(
                    "POST",
                    f"{ALBERT_ENDPOINT}/v1/chat/completions",
                    headers=self.headers,
                    json={
                        "messages": messages,
                        "model": LLM_MODEL,
                        "stream": True,
                    },
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: ") and line.strip() != "data: [DONE]":
                            try:
                                chunk = line[6:]
                                chunk_data = json.loads(chunk)
                                if (
                                    content := chunk_data["choices"][0]
                                    .get("delta", {})
                                    .get("content")
                                ):
                                    yield content
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse chunk: {e}")
                                continue

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
                )
                raise
            except httpx.RequestError as e:
                logger.error(f"Request error occurred: {str(e)}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}", exc_info=True)
                raise

    async def _collect_stream_to_string(self, message: str, system_prompt: str) -> str:
        result = []
        async for token in self._make_request_stream_async(message, system_prompt):
            result.append(token)
        return "".join(result)

    @lru_cache(maxsize=100)
    async def get_summary_async(self, message: str) -> str:
        logger.info("Generating summary for text")
        return await self._collect_stream_to_string(message, self.SUMMARY_PROMPT)

    @lru_cache(maxsize=100)
    async def get_keywords_async(self, message: str) -> str:
        logger.info("Extracting keywords from text")
        return await self._collect_stream_to_string(message, self.KEYWORD_PROMPT)

    @lru_cache(maxsize=100)
    async def get_questions_async(self, message: str) -> str:
        logger.info("Generating questions from text")
        return await self._collect_stream_to_string(message, self.QUESTION_PROMPT)

    async def get_answer_stream_async(
        self,
        message: str,
        documents: ChunkDataListWithDocument,
        conversation_history: Optional[list] = None,
    ) -> AsyncGenerator[str, None]:
        logger.info("Generating streaming answer based on documents")
        document_contents = [item["content"] for item in documents["data"]]
        system_prompt = self.LLM_PROMPT.replace(
            "[DOCUMENTS]", "\n".join(document_contents)
        )
        async for token in self._make_request_stream_async(
            message, system_prompt, conversation_history
        ):
            yield token

    def get_summary(self, message: str) -> str:
        async def _wrapped():
            async with self:
                return await self.get_summary_async(message)

        return asyncio.run(_wrapped())

    def get_keywords(self, message: str) -> str:
        async def _wrapped():
            async with self:
                return await self.get_keywords_async(message)

        return asyncio.run(_wrapped())

    def get_questions(self, message: str) -> str:
        async def _wrapped():
            async with self:
                return await self.get_questions_async(message)

        return asyncio.run(_wrapped())

    def get_answer_stream(
        self,
        message: str,
        documents: ChunkDataListWithDocument,
        conversation_history: Optional[list] = None,
    ) -> Iterator[str]:
        async def collect_tokens():
            tokens = []
            async with self:
                async for token in self.get_answer_stream_async(
                    message, documents, conversation_history
                ):
                    tokens.append(token)
            return tokens

        return iter(asyncio.run(collect_tokens()))
