"""Chunking of the CDTN documents read from Postgres (ported from the api's
ingestion/data_exploiter_embed.py)."""

import json
import logging
from collections.abc import Iterator

from ingestion.contract import Chunk, SourceName
from ingestion.sources.legi import LegiIndex
from ingestion.sources.models import RawLegiLink, ResolvedLegiLink
from ingestion.sources.postgres import Document
from ingestion.text.chunker import Chunker, ChunkerContentType
from ingestion.text.legi_links import link_from_url, links_from_html

BASE_URL_CDTN = "https://code.travail.gouv.fr"

logger = logging.getLogger(__name__)


class BaseDataExploiter:
    def __init__(self, legi_index: LegiIndex | None = None):
        self.chunker = Chunker()
        self.legi_index = legi_index
        self._legi_stats = {"docs": 0, "links": 0, "resolved": 0}

    def get_content(self, _doc: Document) -> str:
        raise NotImplementedError("Subclasses should implement this method")

    def get_legi_links(self, _doc: Document) -> list[RawLegiLink]:
        """Legifrance /codes/ links of the document, structured fields first
        (their label is the one kept when deduplicating)."""
        return []

    def extract_legi_links(self, doc: Document) -> list[ResolvedLegiLink]:
        if self.legi_index is None:
            return []
        return self.legi_index.resolve_all(self.get_legi_links(doc))

    def process_documents(
        self,
        data: list[Document],
        chunker_content_type: ChunkerContentType,
    ) -> list[Chunk]:
        chunk_list: list[Chunk] = []

        for doc in data:
            content = self.get_content(doc)
            splits = self.chunker.split(content, chunker_content_type)
            legi_links = self.extract_legi_links(doc)
            self._log_legi_links(legi_links)
            url = (
                BASE_URL_CDTN
                + "/"
                + _get_path_from_collection_name(doc.source)
                + "/"
                + doc.slug
            )

            for idx, split in enumerate(splits):
                chunk_list.append(
                    Chunk.model_validate(
                        {
                            "content": split.page_content,
                            "id": doc.cdtn_id,
                            "metadata": {
                                "idx": idx,
                                "id": doc.cdtn_id,
                                "initial_id": doc.initial_id,
                                "url": url,
                                "source": doc.source,
                                "title": doc.title,
                                "idcc": doc.idcc,
                                "articles": None,
                                "legi_links": legi_links,
                            },
                        }
                    )
                )

        self._report_legi_links(data)
        return chunk_list

    def _log_legi_links(self, links: list[ResolvedLegiLink]):
        stats = self._legi_stats
        stats["docs"] += bool(links)
        stats["links"] += len(links)
        stats["resolved"] += sum(1 for link in links if link["cid"])

    def _report_legi_links(self, data: list[Document]):
        stats = self._legi_stats
        if self.legi_index is not None and data:
            logger.info(
                f"{data[0].source}: {stats['links']} legifrance /codes/ links "
                f"in {stats['docs']}/{len(data)} documents, "
                f"{stats['resolved']} resolved in the code du travail"
            )
        self._legi_stats = {"docs": 0, "links": 0, "resolved": 0}


def _get_path_from_collection_name(collection_name: SourceName) -> str:
    mapping: dict[SourceName, str] = {
        "fiches_service_public": "fiche-service-public",
        "page_fiche_ministere_travail": "fiche-ministere-travail",
        "information": "information",
        "contributions": "contribution",
        "contributions_idcc": "contribution",
    }
    return mapping[collection_name]


class FichesMTExploiter(BaseDataExploiter):
    def get_content(self, doc: Document) -> str:
        return "".join(
            section.get("html", "") for section in doc.document.get("sections", [])
        )

    def get_legi_links(self, doc: Document) -> list[RawLegiLink]:
        sections = doc.document.get("sections") or []
        links = [
            link_from_url(ref.get("url"), ref.get("title"), "sections.references")
            for section in sections
            for ref in section.get("references") or []
        ]
        for section in sections:
            links += links_from_html(section.get("html"), "sections.html")
        links += links_from_html(doc.document.get("intro"), "intro")
        return [link for link in links if link]


# service-public XML elements carrying a link (URL attribute)
SP_LINK_ELEMENTS = ("Reference", "LienExterne")


def _sp_text(node) -> str:
    if node.get("type") == "text":
        return node.get("text", "")
    return "".join(_sp_text(child) for child in node.get("children") or [])


def _sp_link_elements(node) -> Iterator[dict]:
    if node.get("name") in SP_LINK_ELEMENTS:
        yield node
    for child in node.get("children") or []:
        yield from _sp_link_elements(child)


class FichesSPExploiter(BaseDataExploiter):
    def get_content(self, doc: Document) -> str:
        return doc.text

    def get_legi_links(self, doc: Document) -> list[RawLegiLink]:
        # referencedTexts is a subset of the raw XML Reference elements
        raw = doc.document.get("raw")
        if not raw:
            return []
        links = []
        for node in _sp_link_elements(json.loads(raw)):
            titre = next(
                (c for c in node.get("children") or [] if c.get("name") == "Titre"),
                None,
            )
            label = _sp_text(titre if titre is not None else node)
            url = (node.get("attributes") or {}).get("URL")
            links.append(link_from_url(url, label, f"raw:{node['name']}"))
        return [link for link in links if link]


class PageInfosExploiter(BaseDataExploiter):
    def get_content(self, doc: Document) -> str:
        markdown = ""
        for content in doc.document.get("contents", []):
            for block in content.get("blocks", []):
                if block.get("type") == "markdown":
                    markdown += block.get("markdown", "")
        return markdown

    def get_legi_links(self, doc: Document) -> list[RawLegiLink]:
        links = [
            link_from_url(link.get("url"), link.get("title"), "references")
            for ref in doc.document.get("references") or []
            for link in ref.get("links") or []
        ]
        links += [
            link_from_url(link.get("url"), link.get("title"), "contents.references")
            for content in doc.document.get("contents") or []
            for ref in content.get("references") or []
            for link in ref.get("links") or []
        ]
        return [link for link in links if link]


class PagesContributionsExploiter(BaseDataExploiter):
    def get_content(self, doc: Document) -> str:
        return doc.document["content"]

    def get_legi_links(self, doc: Document) -> list[RawLegiLink]:
        links = [
            link_from_url(ref.get("url"), ref.get("title"), "references")
            for ref in doc.document.get("references") or []
        ]
        links += links_from_html(doc.document.get("content"), "content")
        return [link for link in links if link]


# exploiter and chunker content type of each CDTN source
CDTN_SOURCES: dict[SourceName, tuple[type[BaseDataExploiter], ChunkerContentType]] = {
    "contributions": (PagesContributionsExploiter, "html"),
    "contributions_idcc": (PagesContributionsExploiter, "html_contribs"),
    "information": (PageInfosExploiter, "markdown"),
    "page_fiche_ministere_travail": (FichesMTExploiter, "html"),
    "fiches_service_public": (FichesSPExploiter, "character_recursive"),
}


def chunk_cdtn(
    source: SourceName, documents: list[Document], legi_index: LegiIndex | None
) -> list[Chunk]:
    exploiter_class, content_type = CDTN_SOURCES[source]
    return exploiter_class(legi_index).process_documents(documents, content_type)
