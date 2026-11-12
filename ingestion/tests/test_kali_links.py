import pytest

from ingestion.text.kali_links import link_from_url, parse_kali_url

ART = "KALIARTI000045270882"
CONT = "KALICONT000005635405"
BASE = "https://www.legifrance.gouv.fr"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            f"https://legifrance.gouv.fr/conv_coll/id/{ART}/?idConteneur={CONT}",
            (ART, CONT),
        ),
        (f"{BASE}/conv_coll/article/{ART}#{ART}", (ART, None)),
        (
            f"{BASE}/conv_coll/article/{ART}?idConteneur={CONT}&origin=list#{ART}",
            (ART, CONT),
        ),
        (f"{BASE}/conv_coll/id/{ART}?cidKaliCont={CONT}&query=mi-temps", (ART, CONT)),
        (
            f"{BASE}/conv_coll/id/KALITEXT000043000001/?idConteneur={CONT}",
            ("KALITEXT000043000001", CONT),
        ),
        (f"{BASE}/conv_coll/id/KALISCTA000043000002", ("KALISCTA000043000002", None)),
        (f" {BASE}/conv_coll/article/{ART}#{ART}", (ART, None)),
        # legacy urls: target in the query, section before text
        (
            f"{BASE}/affichIDCC.do;jsessionid=C6E78561AB60D1D67B3304C0EFE9B4DF.tplgfr30s_3"
            f"?idSectionTA=KALISCTA000043000002&cidTexte=KALITEXT000043000001&idConvention={CONT}",
            ("KALISCTA000043000002", CONT),
        ),
        (
            f"{BASE}/affichIDCC.do?cidTexte=KALITEXT000043000001&idConvention={CONT}",
            ("KALITEXT000043000001", CONT),
        ),
        # Google Docs redirect
        (
            f"https://www.google.com/url?q={BASE}/conv_coll/article/{ART}%23{ART}&sa=D",
            (ART, None),
        ),
    ],
)
def test_parse_kali_url(url, expected):
    assert parse_kali_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        f"{BASE}/codes/article_lc/LEGIARTI000000000010",
        f"{BASE}/juri/id/JURITEXT000007038010",
        f"{BASE}/conv_coll/id/{CONT}",  # a whole agreement: no target
        f"https://code.travail.gouv.fr/code-du-travail/l1226-9?x={ART}",
        f"https://example.org/conv_coll/id/{ART}",
    ],
)
def test_parse_kali_url_ignores_other_links(url):
    assert parse_kali_url(url) is None


def test_link_from_url_keeps_url_and_label():
    url = f" {BASE}/conv_coll/id/{ART}/?idConteneur={CONT} "
    assert link_from_url(url, "  Article 7.03  ", "references") == {
        "kali_id": ART,
        "url": url.strip(),
        "label": "Article 7.03",
        "origin": "references",
        "container": CONT,
    }
    assert link_from_url(None, "x", "references") is None
    assert link_from_url(url, "  ", "references")["label"] is None
