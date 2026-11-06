import tiktoken

from srdt_analysis.core.settings import get_settings


class Tokenizer:
    def __init__(self):
        self._tokenizer = tiktoken.get_encoding(get_settings().tiktoken_tokenizer_model)

    def compute_nb_tokens(self, text: str) -> int:
        tokens = self._tokenizer.encode(text)
        return len(tokens)
