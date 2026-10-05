"""Extract Legifrance links pointing to a code
(https://www.legifrance.gouv.fr/codes/...), without resolution nor filtering.
"""

from typing import Optional

import regex
from bs4 import BeautifulSoup

from srdt_analysis.core.models import RawLegiLink

LEGI_CODES_URL = regex.compile(
    r"https?://(?:www\.)?legifrance\.gouv\.fr/codes/[^\s\"'<>)\]]+"
)
LEGI_ID = regex.compile(r"LEGI(?:ARTI|SCTA)\d{12}")


def parse_legi_id(url: str) -> Optional[str]:
    """Last LEGIARTI/LEGISCTA id of the url. Handles article_lc/X, id/X,
    section_lc/LEGITEXT…/X, as well as date suffixes and query strings.
    """
    if not LEGI_CODES_URL.match(url.strip()):
        return None
    ids = LEGI_ID.findall(url)
    return ids[-1] if ids else None


def link_from_url(
    url: Optional[str], label: Optional[str], origin: str
) -> Optional[RawLegiLink]:
    if not url:
        return None
    legi_id = parse_legi_id(url)
    if legi_id is None:
        return None
    return {
        "legi_id": legi_id,
        "url": url.strip(),
        "label": label.strip() if label and label.strip() else None,
        "origin": origin,
    }


def links_from_html(html: Optional[str], origin: str) -> list[RawLegiLink]:
    """<a href> links (label = link text), then plain urls found in the text."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    links: list[RawLegiLink] = []
    for a in soup.find_all("a", href=True):
        link = link_from_url(str(a["href"]), a.get_text(" ", strip=True), origin)
        if link:
            links.append(link)
    for url in LEGI_CODES_URL.findall(soup.get_text(" ")):
        link = link_from_url(url.rstrip(".,;:"), None, origin)
        if link:
            links.append(link)
    return links
