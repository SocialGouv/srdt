import json
import os

from dotenv import load_dotenv

from srdt_analysis.clients.collections import AlbertCollectionHandler
from srdt_analysis.clients.judilibre_client import get_decision_url
from srdt_analysis.core.models import Chunk
from srdt_analysis.ingestion.data_exploiter_embed import make_batches
from srdt_analysis.text.chunker import Chunker

load_dotenv()

DATA_DIR = "judilibre"

_chunker = Chunker()
_albert = AlbertCollectionHandler()


def chunk_decision(decision):
    chunks = []
    decision_id = decision.get("id")

    for ts_idx, ts in enumerate(decision.get("titlesAndSummaries") or []):
        summary = ts.get("summary")
        if not summary:
            continue

        titles = ts.get("titles") or []
        header = " > ".join(titles)
        content = f"{header}\n{summary}" if header else summary

        for idx, split in enumerate(_chunker.split_character_recursive(content)):
            chunks.append(
                {
                    "id": f"{decision_id}-{ts_idx}",
                    "idx": idx,
                    "title": ",".join(titles) if titles else decision.get("number"),
                    "decision_id": decision_id,
                    "content": split.page_content,
                }
            )

    return chunks


def embed_judilibre_chunks(chunks) -> list[Chunk]:
    chunk_list: list[Chunk] = []

    for chunk in chunks:
        chunk_list.append(
            {
                "content": chunk["content"],
                "id": chunk["id"],
                "embedding": None,
                "metadata": {
                    "id": chunk["id"],
                    "source": "judilibre",
                    "url": get_decision_url(chunk["decision_id"]),
                    "initial_id": chunk["decision_id"],
                    "title": chunk["title"],
                    "idx": chunk["idx"],
                    "idcc": None,
                    "articles": [],
                },
            }
        )

    for batch in make_batches(chunk_list, 64):
        contents = [c["content"] for c in batch]
        embeddings = _albert.embeddings(contents)
        for c, emb in zip(batch, embeddings):
            c["embedding"] = emb  # type: ignore

    return chunk_list


def get_judilibre_chunked(data_dir=DATA_DIR) -> list[Chunk]:
    aggregated: list[Chunk] = []

    for filename in os.listdir(data_dir):
        if not filename.endswith(".json"):
            continue

        with open(os.path.join(data_dir, filename)) as f:
            decisions = json.load(f)

        chunks = []
        for decision in decisions:
            chunks.extend(chunk_decision(decision))

        aggregated.extend(embed_judilibre_chunks(chunks))

    return aggregated
