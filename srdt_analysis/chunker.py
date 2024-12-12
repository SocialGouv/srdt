from typing import Callable, Dict, List

from langchain_text_splitters import (
    HTMLHeaderTextSplitter,
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from srdt_analysis.constants import CHUNK_OVERLAP, CHUNK_SIZE
from srdt_analysis.models import ChunkerContentType, SplitDocument


class Chunker:
    def __init__(self):
        self._markdown_splitter = MarkdownHeaderTextSplitter(
            [
                ("#", "Header 1"),
                ("##", "Header 2"),
                ("###", "Header 3"),
                ("####", "Header 4"),
                ("#####", "Header 5"),
                ("######", "Header 6"),
            ],
            strip_headers=False,
        )
        self._html_splitter = HTMLHeaderTextSplitter(
            [
                ("h1", "Header 1"),
                ("h2", "Header 2"),
                ("h3", "Header 3"),
                ("h4", "Header 4"),
                ("h5", "Header 5"),
                ("h6", "Header 6"),
            ]
        )
        self._character_recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
        )

    def split_markdown(self, markdown: str) -> List[SplitDocument]:
        md_header_splits = self._markdown_splitter.split_text(markdown)
        documents = self._character_recursive_splitter.split_documents(md_header_splits)
        return [SplitDocument(doc.page_content, doc.metadata) for doc in documents]

    def split_html(self, html: str) -> List[SplitDocument]:
        html_header_splits = self._html_splitter.split_text(html)
        documents = self._character_recursive_splitter.split_documents(
            html_header_splits
        )
        return [SplitDocument(doc.page_content, doc.metadata) for doc in documents]

    def split_character_recursive(self, content: str) -> List[SplitDocument]:
        text_splits = self._character_recursive_splitter.split_text(content)
        return [SplitDocument(text, {}) for text in text_splits]

    def split(
        self,
        content: str,
        content_type: ChunkerContentType,
    ) -> List[SplitDocument]:
        content_type_to_splitters: Dict[
            ChunkerContentType, Callable[[str], List[SplitDocument]]
        ] = {
            "markdown": self.split_markdown,
            "html": self.split_html,
            "character_recursive": self.split_character_recursive,
        }
        splitter_func = content_type_to_splitters.get(content_type)
        if splitter_func is None:
            raise ValueError(f"Unsupported content type: {content_type}")
        return splitter_func(content)
