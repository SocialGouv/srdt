from typing import Literal, TypedDict

# Legifrance links to a code (https://www.legifrance.gouv.fr/codes/...)
LegiKind = Literal["article", "section"]


class RawLegiLink(TypedDict):
    legi_id: str
    url: str
    label: str | None
    origin: str


class ResolvedLegiLink(RawLegiLink):
    # resolved against the code du travail (LEGI), None if outside of it
    kind: LegiKind | None
    cid: str | None
    num: str | None
    chunk_id: str | None
    canonical_url: str | None


# Legifrance links to a collective agreement text
# (https://www.legifrance.gouv.fr/conv_coll/...)
KaliKind = Literal["article", "section"]


class RawKaliLink(TypedDict):
    kali_id: str
    url: str
    label: str | None
    origin: str
    # KALICONT id found in the url, if any
    container: str | None


class ResolvedKaliLink(RawKaliLink):
    # resolved against the KALI agreements, None if the id is not in them
    kind: KaliKind | None
    cid: str | None
    num: str | None
    idcc: str | None
    chunk_id: str | None
    canonical_url: str | None
