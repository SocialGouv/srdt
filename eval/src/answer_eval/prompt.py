"""The messages the web sends to the answer model (`/api/generate`, first question).

Port of `createKnowledgeBaseContent`/`formatChunks`
(`web/src/modules/api/prompt-builders.ts`) and of the assembly in `getGenerateData`
(`web/src/modules/api/process.ts`). The instruction templates themselves are not
copied by hand: `scripts/web_prompts.mjs export` extracts them from the TypeScript
sources into `generation/prompts/web-<config>.json`, with the hash of each source
file. `tests/test_answer_prompt.py` renders the same cases with the real TypeScript
code and requires byte-identical output.

Not ported: the follow-up prompts.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

CDTN_CC_URL = "https://code.travail.gouv.fr/convention-collective/"
JUDILIBRE = "judilibre"  # web: Collection.JUDILIBRE


class ChunkMetadata(BaseModel):
    # The API returns more fields (they are kept, the prompt only reads these).
    model_config = ConfigDict(extra="allow")

    id: str
    source: str = ""
    url: str = ""
    title: str = ""


class Chunk(BaseModel):
    """A chunk or a full document, as the web passes it to the prompt builders."""

    model_config = ConfigDict(extra="ignore")

    content: str
    metadata: ChunkMetadata
    # Why this chunk is there: the label grade (fiches) or the rerank score.
    grade: int | None = None
    rerank_score: float | None = None


class WebPrompts:
    """Instruction templates exported from the web sources."""

    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.path = path
        self.config: str = data["config"]
        self.generate_instruction: str = data["generate_instruction"]
        self.generate_instruction_idcc: str = data["generate_instruction_idcc"]
        self.jurisprudence_filter_instruction: str = data.get(
            "jurisprudence_filter_instruction", ""
        )
        self.sources: dict[str, str] = data["sources"]
        self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    def stale_sources(self, repo_root: Path) -> list[str]:
        """Web source files that changed (or vanished) since the export."""
        stale = []
        for rel, digest in self.sources.items():
            path = repo_root / rel
            if (
                not path.exists()
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest
            ):
                stale.append(rel)
        return stale


def _format_decision_date(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if not match:
        return raw
    year, month, day = match.groups()
    return f"{day}/{month}/{year}"


def chunk_title(chunk: Chunk) -> str:
    """Port of `chunkTitle`: a decision is cited by its number and date, else by its
    identifier."""
    metadata = chunk.metadata
    if metadata.source != JUDILIBRE:
        return metadata.title
    extra = metadata.model_extra or {}
    number = extra.get("number")
    date = _format_decision_date(extra.get("decision_date"))
    if isinstance(number, str) and number and date:
        return f"Arrêt numéro {number} du {date}"
    initial_id = extra.get("initial_id")
    decision_id = (
        initial_id if initial_id is not None else re.sub(r"-\d+$", "", metadata.id)
    )
    return f"Arrêt de la Cour de cassation (réf. {decision_id})"


def format_chunks(chunks: list[Chunk]) -> str:
    return "\n".join(
        f"Source: {c.metadata.source} ({c.metadata.url})\n"
        f"Titre: {chunk_title(c)}\n"
        f"Contenu: {c.content}\n"
        "---"
        for c in chunks
    )


def knowledge_base_content(
    fiches: list[Chunk],
    code: list[Chunk],
    idcc_chunks: list[Chunk] | None,
    jurisprudence: list[Chunk] | None = None,
) -> str:
    content = f"""# Base de connaissance externe
Plusieurs types de documents sont ajoutés dans la base de connaissance externe

## Fiches officielles (1 à 10 extraits) :

Sources : Fiches des services publics, fiches du ministère du travail, contributions des pages du Code du travail numérique.

Caractéristiques : Ces articles sont rédigés ou validés par des professionnels du droit et offrent une synthèse fiable.

{format_chunks(fiches)}

## Code du travail (1 à 5 extraits) :

Sources : Sections entières du Code du travail.

Caractéristiques : Textes légaux officiels.

{format_chunks(code)}"""  # noqa: E501

    if idcc_chunks:
        content += f"""

## Conventions collectives (1 à 5 extraits, si applicable) :

Sources : Pages du Code du travail numérique dédiées aux conventions collectives.

Caractéristiques : Spécifiques à la convention collective mentionnée par l'utilisateur (via son IDCC).

Utilisation : Utiliser ces sources uniquement si l'utilisateur a fourni l'IDCC de sa convention collective. Inclure un paragraphe dédié dans la réponse et un lien vers la convention collective dans la conclusion.

{format_chunks(idcc_chunks)}"""  # noqa: E501

    if jurisprudence:
        content += f"""

## Jurisprudence (0 à 5 extraits) :

Sources : Décisions de la Cour de cassation, chambre sociale, publiées au bulletin (sommaires).

Caractéristiques : Décisions faisant autorité. Base **complémentaire** : la réponse se fonde d'abord sur les fiches officielles et le Code du travail. N'utiliser ces extraits que selon les règles de la section "⚖️ Jurisprudence" des instructions (contradiction, précision, ou seule source disponible). Sinon, ne pas les mentionner.

{format_chunks(jurisprudence)}"""  # noqa: E501

    return content


def system_prompt(
    prompts: WebPrompts,
    *,
    idcc: str | None,
    idcc_name: str | None,
    fiches: list[Chunk],
    code: list[Chunk],
    idcc_chunks: list[Chunk],
    jurisprudence: list[Chunk] | None = None,
) -> str:
    kb = knowledge_base_content(
        fiches, code, idcc_chunks if idcc else None, jurisprudence
    )
    if not idcc:
        return prompts.generate_instruction + "\n\n" + kb
    template = (
        prompts.generate_instruction_idcc
        # JS String.replace with a string pattern: first occurrence only.
        .replace("[URL_convention_collective]", f"{CDTN_CC_URL}{idcc}", 1)
        .replace("${IDCC_NAME}", idcc_name or "")
        .replace("${IDCC_NUMBER}", idcc)
    )
    return template + "\n\n" + kb


def messages(system: str, question: str) -> list[dict[str, Any]]:
    """`createChatHistory`/`createIdccChatHistory`: the bare question."""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
