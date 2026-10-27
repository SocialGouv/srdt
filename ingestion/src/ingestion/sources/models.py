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
