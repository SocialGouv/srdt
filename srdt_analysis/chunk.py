from typing import List

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from srdt_analysis.constants import CHUNK_OVERLAP, CHUNK_SIZE
from srdt_analysis.models import SplitDocument


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
        self._character_recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
        )

    def split_markdown(self, markdown: str) -> List[SplitDocument]:
        md_header_splits = self._markdown_splitter.split_text(markdown)
        return self._character_recursive_splitter.split_documents(md_header_splits)

    def split_character_recursive(self, content: str) -> List[SplitDocument]:
        return self._character_recursive_splitter.split_text(content)

    def split(self, content: str, content_type: str = "markdown"):
        if content_type.lower() == "markdown":
            return self.split_markdown(content)
        raise ValueError(f"Unsupported content type: {content_type}")
