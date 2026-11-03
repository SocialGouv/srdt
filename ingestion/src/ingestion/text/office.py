"""Plain text of .docx and .odt files, one line per paragraph (standard library only).

Used when the text extracted by the Légifrance API is cut at 100,000 characters.
"""

import zipfile
from pathlib import Path
from xml.etree import ElementTree

# the originals are untrusted: refuse a part that inflates beyond this
MAX_PART_BYTES = 100 * 1024 * 1024

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


class OfficeError(RuntimeError):
    pass


def _read_part(path: Path, name: str) -> ElementTree.Element:
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo(name)
            if info.file_size > MAX_PART_BYTES:
                raise OfficeError(f"{path.name}: {name} is too large")
            return ElementTree.fromstring(archive.read(info))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as error:
        raise OfficeError(f"{path.name}: cannot read {name}: {error}") from error


def _docx_paragraph(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for element in paragraph.iter():
        if element.tag == f"{W}t":
            parts.append(element.text or "")
        elif element.tag == f"{W}tab":
            parts.append("\t")
        elif element.tag in (f"{W}br", f"{W}cr"):
            parts.append("\n")
    return "".join(parts)


def _odt_text(element: ElementTree.Element) -> str:
    parts = [element.text or ""]
    for child in element:
        if child.tag == f"{TEXT}s":
            parts.append(" " * int(child.get(f"{TEXT}c", "1")))
        elif child.tag == f"{TEXT}tab":
            parts.append("\t")
        elif child.tag == f"{TEXT}line-break":
            parts.append("\n")
        else:
            parts.append(_odt_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def extract_text(path: Path) -> str:
    """The text of a .docx or .odt file, paragraphs (and table cells) on their own
    lines."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        root = _read_part(path, "word/document.xml")
        paragraphs = [_docx_paragraph(p) for p in root.iter(f"{W}p")]
    elif suffix == ".odt":
        root = _read_part(path, "content.xml")
        paragraphs = [
            _odt_text(p) for p in root.iter() if p.tag in (f"{TEXT}p", f"{TEXT}h")
        ]
    else:
        raise OfficeError(f"{path.name}: unsupported file type")
    return "\n".join(paragraphs)
