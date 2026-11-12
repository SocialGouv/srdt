from srdt_analysis.text.article_citations import extract_article_citations


def nums(question: str) -> list[str]:
    return [c.num for c in extract_article_citations(question)]


def codes(question: str) -> list[str]:
    return [c.code for c in extract_article_citations(question)]


def test_standard_with_code_name():
    cites = extract_article_citations("Que dit l'article R2315-25 du code du travail ?")
    assert [(c.num, c.code, c.kind) for c in cites] == [
        ("R2315-25", "travail", "article")
    ]


def test_dot_and_space_after_the_letter():
    assert nums("l'article L. 1226-14 est-il applicable ?") == ["L1226-14"]
    assert nums("l'article R.4624-10") == ["R4624-10"]


def test_number_alone_is_unknown_code():
    assert codes("Selon l'article R. 4624-10, le médecin du travail ...") == ["unknown"]


def test_nested_hyphens_and_special_hyphens():
    assert nums("article L3141-19-1 et L1226–14 et D1234‑5") == [
        "L3141-19-1",
        "L1226-14",
        "D1234-5",
    ]


def test_code_named_before_the_number():
    cites = extract_article_citations("(C. trav., art L3141-8)")
    assert [(c.num, c.code) for c in cites] == [("L3141-8", "travail")]


def test_list_gives_one_citation_per_number():
    cites = extract_article_citations(
        "les articles L. 1226-14 et L. 1226-15 du code du travail"
    )
    assert [(c.num, c.code) for c in cites] == [
        ("L1226-14", "travail"),
        ("L1226-15", "travail"),
    ]


def test_range_and_following_are_flagged():
    cites = extract_article_citations("articles L. 2232-1 à L. 2232-4")
    assert [(c.num, c.kind) for c in cites] == [
        ("L2232-1", "range-start"),
        ("L2232-4", "range-end"),
    ]
    cites = extract_article_citations("L. 3141-19-1 et suivants du code du travail")
    assert [(c.num, c.kind) for c in cites] == [("L3141-19-1", "following")]


def test_lowercase_letter_only_after_article():
    assert nums("l'article l1225-14 code du travail") == ["L1225-14"]
    assert nums("le l1225-14 ou d1234-5") == []


def test_other_code_is_flagged():
    assert codes("l'article L. 225-2 du code de l'action sociale") == ["other"]
    assert codes("l'article L. 761-1 du CJA") == ["other"]
    assert codes("l'article R323-10 du code de la sécurité sociale") == ["other"]


def test_each_citation_gets_the_code_that_follows_it():
    cites = extract_article_citations(
        "l'article L. 1226-14 du code du travail et l'article L. 225-2 du code de l'action sociale"
    )
    assert [(c.num, c.code) for c in cites] == [
        ("L1226-14", "travail"),
        ("L225-2", "other"),
    ]


def test_same_code_inherits_the_previous_one():
    cites = extract_article_citations(
        "l'article L. 2122-1 du code de la santé publique et l'article L. 2122-2 du même code"
    )
    assert [c.code for c in cites] == ["other", "other"]


def test_letterless_number_needs_the_code_name_nearby():
    cites = extract_article_citations("articles 4121-1 et 4121-2 du code du travail")
    assert [(c.num, c.has_letter) for c in cites] == [
        ("4121-1", False),
        ("4121-2", False),
    ]
    assert nums("le montant est de 2023-12 euros") == []


def test_no_citation():
    for question in [
        "Article 9.5 de la convention collective",
        "Art. 19 modifié par avenant n° 30",
        "le groupe du3 et le niveau LV2",
        "le poste D828 ou R482",
        "j'ai travaillé d'1 à 3 ans, L 12 jours",
        "pouvez-vous me donner un texte de loi ?",
        "",
    ]:
        assert extract_article_citations(question) == [], question
