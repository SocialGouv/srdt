"""Extract Legifrance links pointing to a collective agreement
(https://www.legifrance.gouv.fr/conv_coll/...), without resolution nor filtering.
"""

from urllib.parse import parse_qs, urlsplit

import regex

from ingestion.sources.models import RawKaliLink

# conv_coll/id/X, conv_coll/article/X and the legacy affichIDCC.do?...
KALI_URL = regex.compile(
    r"https?://(?:www\.)?legifrance\.gouv\.fr/(?:conv_coll/|affichIDCC\.do)"
)
KALI_ID = regex.compile(r"KALI(?:ARTI|TEXT|SCTA)\d{12}")
KALI_CONTAINER = regex.compile(r"KALICONT\d{12}")

# legacy urls carry the target in the query, most specific first
TARGET_PARAMS = ("idSectionTA", "cidTexte")
CONTAINER_PARAMS = ("idConteneur", "idConvention", "cidKaliCont")


def _unwrap_redirect(url: str) -> str:
    """The Google Docs redirect (google.com/url?q=...) around a Legifrance url."""
    parts = urlsplit(url)
    if parts.netloc.endswith("google.com") and parts.path == "/url":
        target = parse_qs(parts.query).get("q")
        if target:
            return target[0].strip()
    return url


def parse_kali_url(url: str) -> tuple[str, str | None] | None:
    """(target id, container id) of a Legifrance agreement url, None if it is
    not one or has no KALIARTI/KALITEXT/KALISCTA target. The target is the id of
    the path (a `;jsessionid` suffix is ignored), else the one of the query.
    """
    url = _unwrap_redirect(url.strip())
    if not KALI_URL.match(url):
        return None
    parts = urlsplit(url)
    query = parse_qs(parts.query)

    match = KALI_ID.search(parts.path)
    target = match.group() if match else None
    if target is None:
        for param in TARGET_PARAMS:
            match = next(
                (v for v in query.get(param, []) if KALI_ID.fullmatch(v)), None
            )
            if match:
                target = match
                break
    if target is None:
        return None

    container = next(
        (
            v
            for param in CONTAINER_PARAMS
            for v in query.get(param, [])
            if KALI_CONTAINER.fullmatch(v)
        ),
        None,
    )
    return target, container


def link_from_url(
    url: str | None, label: str | None, origin: str
) -> RawKaliLink | None:
    if not url:
        return None
    parsed = parse_kali_url(url)
    if parsed is None:
        return None
    kali_id, container = parsed
    return {
        "kali_id": kali_id,
        "url": url.strip(),
        "label": label.strip() if label and label.strip() else None,
        "origin": origin,
        "container": container,
    }
