import os

import tiktoken


class Tokenizer:
    def __init__(self):
        model = os.getenv("TIKTOKEN_TOKENIZER_MODEL")
        if model is None:
            raise ValueError("TIKTOKEN_TOKENIZER_MODEL environment variable is not set")
        self._tokenizer = tiktoken.get_encoding(model)

    def compute_nb_tokens(self, text: str) -> int:
        tokens = self._tokenizer.encode(text)
        return len(tokens)
