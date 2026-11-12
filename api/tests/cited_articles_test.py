from srdt_analysis.api.schemas import ChunkMetadata, ChunkResult
from srdt_analysis.clients.elastic_handler import ArticleChunk
from srdt_analysis.services.cited_articles import find_cited_articles


def hit(id_chunk: str, idx: int, nums: list[str], content: str) -> ArticleChunk:
    return ArticleChunk(
        chunk=ChunkResult(
            score=0.0,
            content=content,
            id_chunk=id_chunk,
            metadata=ChunkMetadata(
                title="Code du travail", url="u", id="doc", source="code_du_travail"
            ),
        ),
        idx=idx,
        nums=nums,
    )


class FakeEs:
    def __init__(self, hits: list[ArticleChunk]):
        self.hits = hits
        self.asked: list[str] = []

    def get_chunks_by_articles(self, index_name, nums):
        self.asked = nums
        return [h for h in self.hits if set(h.nums) & set(nums)]


SECTION = ["L4121-1", "L4121-2", "L4121-3", "L4121-4"]
HITS = [
    hit("s0", 0, SECTION, "Article L4121-1 \n texte\nArticle L4121-2 \n texte"),
    hit("s1", 1, SECTION, "suite de l'article L. 4121-2"),
    hit("s2", 2, SECTION, "Article L4121-3 \n texte"),
    hit("r0", 0, ["R4121-1"], "Article R4121-1 \n texte"),
]


def test_picks_the_chunk_holding_the_article_text():
    es = FakeEs(HITS)
    chunks, citations = find_cited_articles(
        "l'article L4121-3 du code du travail", es, 5
    )
    assert [c.id_chunk for c in chunks] == ["s2"]
    assert [(c.num, c.found) for c in citations] == [("L4121-3", True)]


def test_articles_of_one_section_do_not_duplicate_the_chunk():
    chunks, _ = find_cited_articles(
        "articles L4121-1 et L4121-2 du code du travail", FakeEs(HITS), 5
    )
    assert [c.id_chunk for c in chunks] == ["s0"]


def test_chunks_follow_the_order_of_the_citations():
    chunks, _ = find_cited_articles("R4121-1 puis L4121-3", FakeEs(HITS), 5)
    assert [c.id_chunk for c in chunks] == ["r0", "s2"]


def test_other_code_is_never_searched():
    es = FakeEs(HITS)
    chunks, citations = find_cited_articles(
        "l'article L4121-1 du code de la sécurité sociale", es, 5
    )
    assert chunks == [] and es.asked == []
    assert [(c.num, c.found) for c in citations] == [("L4121-1", False)]


def test_letterless_number_tries_each_letter():
    es = FakeEs(HITS)
    chunks, citations = find_cited_articles(
        "l'article 4121-1 du code du travail", es, 5
    )
    assert es.asked == ["L4121-1", "R4121-1", "D4121-1"]
    assert [c.id_chunk for c in chunks] == ["s0", "r0"]
    assert [c.found for c in citations] == [True]


def test_article_missing_from_the_index_is_reported():
    chunks, citations = find_cited_articles("l'article L1237-18", FakeEs(HITS), 5)
    assert chunks == []
    assert [(c.num, c.found) for c in citations] == [("L1237-18", False)]


def test_section_without_marker_falls_back_to_its_first_chunk():
    hits = [hit("a1", 1, ["L1111-1"], "texte"), hit("a0", 0, ["L1111-1"], "début")]
    chunks, _ = find_cited_articles("L1111-1", FakeEs(hits), 5)
    assert [c.id_chunk for c in chunks] == ["a0"]


def test_max_chunks_caps_the_result():
    chunks, citations = find_cited_articles("R4121-1 puis L4121-3", FakeEs(HITS), 1)
    assert [c.id_chunk for c in chunks] == ["r0"]
    assert all(c.found for c in citations)


def test_chunk_score_is_set_to_one():
    chunks, _ = find_cited_articles("L4121-3", FakeEs(HITS), 5)
    assert chunks[0].score == 1.0
