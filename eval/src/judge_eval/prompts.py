"""Versioned prompt files -> chat messages."""

import hashlib
import re
from pathlib import Path

from judge_eval.data import CRITERIA, Criterion, Item

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _read(path: Path) -> str:
    # HTML comments are notes for maintainers and are not sent to the model.
    return _HTML_COMMENT.sub("", path.read_text(encoding="utf-8")).strip()


class PromptBook:
    """Prompts of one version: `prompts/<version>/{system,user,<criterion>}.fr.md`."""

    def __init__(self, root: Path, version: str):
        directory = root / version
        if not directory.is_dir():
            raise FileNotFoundError(f"Prompt version not found: {directory}")
        self.version = version
        files = {
            "system": directory / "system.fr.md",
            "user": directory / "user.fr.md",
            **{c.value: directory / f"{c.value}.fr.md" for c in CRITERIA},
        }
        self._text = {name: _read(path) for name, path in files.items()}
        # Detects an edited prompt reusing an old version name.
        digest = hashlib.sha256()
        for name in sorted(files):
            digest.update(files[name].read_bytes())
        self.sha256 = digest.hexdigest()

    def render(self, item: Item, criterion: Criterion) -> list[dict[str, str]]:
        system = f"{self._text['system']}\n\n{self._text[criterion.value]}"
        user = self._text["user"].format(
            question=item.question.strip(), answer=item.answer.strip()
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
