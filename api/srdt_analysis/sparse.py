from typing import List, cast

import bm25s
import spacy
from bm25s.tokenization import Tokenized, Tokenizer
from ranx import Run, fuse

from srdt_analysis.api.schemas import ChunkResult
from srdt_analysis.corpus import getDocs

nlp_fr = spacy.load("fr_core_news_md")


def preprocess(chunks: List[str]):
    fulltext = " ".join(chunks)
    tokens = nlp_fr(fulltext)
    res = []
    for token in tokens:
        if not token.is_punct and not token.is_space and not token.is_stop:
            res.append(token.lemma_)
    return " ".join(res).lower()


def row_to_chunk(docs, cdtn_id, score) -> ChunkResult:
    doc = docs[docs["cdtn_id"] == cdtn_id].to_dict(orient="records")[0]
    return cast(
        ChunkResult,
        {
            "score": score,
            "id_chunk": 1,
            "content": " ".join(doc["content_chunked"]),
            "metadata": {
                "source": doc["source"],
                "title": doc["title"],
                "idcc": doc["idcc"],
                "url": doc["url"],
                "id": doc["cdtn_id"],
                "document_id": doc["cdtn_id"],
            },
        },
    )


class SparseRetriever:
    def __init__(self):
        docs = getDocs()
        self.tokenizer = Tokenizer()

        # for now we use hybrid search only for generic editorial content (no article / no idcc)
        self.indexed_docs = docs[
            ~docs.source.isin(["code_du_travail"])
            & (docs.idcc.isna() | (docs.idcc == "0000"))
        ].reset_index(inplace=False)

        indexed_list = self.indexed_docs["sparse_prepro"].to_list()
        spt = self.tokenizer.tokenize(cast(List[str], indexed_list))

        self.retriever = bm25s.BM25()
        self.retriever.index(spt)

    def search_bm25(self, query: str, top_k: int):
        preprocessed_query = preprocess([query])
        tokens = self.tokenizer.tokenize([preprocessed_query])
        results, scores = self.retriever.retrieve(cast(Tokenized, tokens), k=top_k)

        matches = []
        for r, s in zip(results[0], scores[0]):
            doc = self.indexed_docs.iloc[r]
            c = {
                "chunk": {
                    "metadata": {"url": doc["url"], "id": doc["cdtn_id"]},
                    # temporary
                    "content": " ".join(doc["content_chunked"])[0:100],
                },
                "score": s.item(),
            }
            matches.append(c)

        return matches

    def combined_search(
        self, query, top_k, dense_results: List[ChunkResult]
    ) -> List[ChunkResult]:
        sparse_results = self.search_bm25(query, top_k)

        k = "q"

        formatted_albert = {c.metadata.id: c.score for c in dense_results}
        run_albert = Run({k: formatted_albert})

        formatted_bm25 = {
            c["chunk"]["metadata"]["id"]: c["score"] for c in sparse_results
        }
        run_bm25 = Run({k: formatted_bm25})

        combined_test_run = fuse(
            runs=[run_albert, run_bm25], norm="min-max", method="rrf"
        )

        return [
            row_to_chunk(self.indexed_docs, id, score)
            for id, score in combined_test_run[k].items()
        ][:top_k]
