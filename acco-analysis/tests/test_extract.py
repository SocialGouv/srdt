from acco_analysis.corpus import Agreement
from acco_analysis.extract import (
    MAX_SECTION_CHARS,
    extract_passages,
    find_anchors,
)


def agreement(text: str) -> Agreement:
    return Agreement(
        id="ACCOTEXT1",
        title="t",
        company="c",
        siret=None,
        sector=None,
        idcc=None,
        nature="ACCORD",
        signed="2024-01-01",
        text=text,
    )


def terms(text: str) -> list[tuple[str, str]]:
    return [(a.term, a.kind) for a in find_anchors(text)]


def test_collection_phrases_and_their_forms():
    assert terms("En cas de canicule ou de fortes chaleurs") == [
        ("canicule", "phrase"),
        ("fortes chaleurs", "phrase"),
    ]
    assert terms("Épisodes caniculaires et vagues de chaleur") == [
        ("caniculaires", "phrase"),
        ("vagues de chaleur", "phrase"),
    ]


def test_variants_are_kept_apart_and_not_counted_twice():
    assert terms("des températures extrêmes") == [("températures extrêmes", "variant")]
    # "fortes chaleurs" is one phrase, not also the variant "chaleurs"
    assert terms("fortes chaleurs") == [("fortes chaleurs", "phrase")]
    assert terms("une source de chaleur") == [("chaleur", "variant")]
    assert terms("Le chauffage et le froid") == []


def test_decomposed_accents_match():
    assert terms("températures élevées") == [("températures élevées", "variant")]


def article(n: int, body: str) -> str:
    return f"Article {n} – Titre {n}\n{body}"


def test_a_short_section_is_one_passage():
    text = "\n".join(
        [
            article(1, "Objet."),
            article(
                2, "Les horaires sont décalés en cas de canicule.\nL'eau est fournie."
            ),
            article(3, "Durée de l'accord."),
        ]
    )
    (passage,) = extract_passages(agreement(text))
    assert passage.heading == "Article 2 – Titre 2"
    assert (
        passage.text
        == "Les horaires sont décalés en cas de canicule.\nL'eau est fournie."
    )
    assert passage.id == "ACCOTEXT1-2"
    assert not passage.windowed and not passage.in_heading
    assert [a.kind for a in passage.anchors] == ["phrase"]
    assert (passage.start, passage.stop) == (0, 2)


def test_a_heading_about_heat_is_an_anchor():
    text = "\n".join(
        [
            article(1, "Objet de l'accord conclu."),
            "Article 2 – Fortes chaleurs\nLes pauses sont allongées.",
            article(3, "Durée de l'accord."),
        ]
    )
    (passage,) = extract_passages(agreement(text))
    assert passage.in_heading and passage.anchors[0].line == -1


def test_a_long_section_is_cut_around_its_anchors():
    filler = ["Une ligne de texte sans rapport avec le sujet."] * 80
    body = (
        filler[:20]
        + ["Mesure en cas de canicule."]
        + filler[20:]
        + ["Autre mesure en cas de fortes chaleurs."]
    )
    assert sum(map(len, body)) > MAX_SECTION_CHARS
    text = "\n".join(
        [article(1, "Objet."), article(2, "\n".join(body)), article(3, "Fin.")]
    )
    first, second = extract_passages(agreement(text))
    assert (first.id, second.id) == ("ACCOTEXT1-2-0", "ACCOTEXT1-2-1")
    assert first.windowed and second.windowed
    assert "Mesure en cas de canicule." in first.text
    assert first.text.count("\n") == 5  # 2 lines before, the anchor, 3 after
    assert first.stop - first.start == 6 and second.start >= first.stop
    assert "Autre mesure" in second.text


def test_nearby_anchors_share_a_window():
    filler = ["Ligne de remplissage assez longue pour peser dans la section." * 3] * 30
    body = filler[:10] + ["canicule."] + ["x."] + ["fortes chaleurs."] + filler[10:]
    text = "\n".join(
        [article(1, "Objet."), article(2, "\n".join(body)), article(3, "Fin.")]
    )
    passages = extract_passages(agreement(text))
    assert len(passages) == 1 and len(passages[0].anchors) == 2


def test_agreement_without_headings_is_windowed():
    lines = ["Ligne de texte sans rapport avec le sujet, assez longue." * 3] * 30
    lines[15] = "En cas de canicule, les horaires sont adaptés."
    (passage,) = extract_passages(agreement("\n".join(lines)))
    assert passage.windowed and passage.heading == ""
    assert "canicule" in passage.text


def test_no_anchor_no_passage():
    assert extract_passages(agreement(article(1, "Texte"))) == []
