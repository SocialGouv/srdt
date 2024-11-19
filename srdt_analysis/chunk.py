class Chunker:
    def __init__(self):
        self._markdown_splitter = None

    def split_markdown(self, markdown: str) -> list[any]:
        """
        Split a markdown document into chunks based on headers.

        Args:
            markdown (str): The markdown document to split

        Returns:
            list[any]: List of markdown chunks
        """
        if self._markdown_splitter is None:
            from langchain_text_splitters import MarkdownHeaderTextSplitter

            self._markdown_splitter = MarkdownHeaderTextSplitter()

        return self._markdown_splitter.split_text(markdown)

    def split(self, content: str, content_type: str = "markdown") -> list[any]:
        """
        Generic split method that handles different content types

        Args:
            content (str): The content to split
            content_type (str): Type of content ("markdown" by default)

        Returns:
            list[any]: List of content chunks
        """
        if content_type.lower() == "markdown":
            return self.split_markdown(content)
        raise ValueError(f"Unsupported content type: {content_type}")
