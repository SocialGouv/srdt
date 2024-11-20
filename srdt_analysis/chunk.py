from langchain_text_splitters import MarkdownHeaderTextSplitter


class Chunker:
    def __init__(self):
        self._markdown_splitter = None

    def split_markdown(self, markdown: str) -> list[any]:
        if self._markdown_splitter is None:
            self._markdown_splitter = MarkdownHeaderTextSplitter()

        return self._markdown_splitter.split_text(markdown)

    def split(self, content: str, content_type: str = "markdown") -> list[any]:
        if content_type.lower() == "markdown":
            return self.split_markdown(content)
        raise ValueError(f"Unsupported content type: {content_type}")
