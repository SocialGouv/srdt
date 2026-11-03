from answer_eval.citations import _norm, check_answer

SOURCES = _norm(
    "Les IJ ne peuvent pas dépasser 41,47 € bruts . Votre salaire est plafonné "
    "à 1,4 fois le montant du Smic ( 2 522,52 € par mois )."
)
KNOWN = {"https://code.travail.gouv.fr/fiche"}


def test_quotes_links_and_unknown_urls():
    text = "\n".join(
        [
            "### Réponse",
            '> *"Les IJ ne peuvent pas dépasser 41,47 € bruts."* — [Fiche](https://code.travail.gouv.fr/fiche)',
            '> *"Les IJ [...] 41,47 € bruts. Votre salaire est plafonné"* — [Fiche](https://code.travail.gouv.fr/fiche)',
            '> *"Les IJ sont toujours de 100 %."* — [Légifrance](https://www.legifrance.gouv.fr/x)',
            "Voir [la fiche](https://code.travail.gouv.fr/fiche).",
        ]
    )
    check = check_answer(text, SOURCES, KNOWN)
    assert (check.quotes, check.verbatim, check.links) == (3, 2, 4)
    assert check.unknown_links == ["https://www.legifrance.gouv.fr/x"]


def test_an_answer_without_citations():
    check = check_answer("Pas de citation.", SOURCES, KNOWN)
    assert (check.quotes, check.verbatim, check.links, check.unknown_links) == (
        0,
        0,
        0,
        [],
    )


def test_report_has_a_citations_table():
    from answer_eval.citations import CitationCheck
    from answer_eval.contexts import Context
    from answer_eval.generate import Answer
    from answer_eval.report import build_report

    context = Context(
        query_id="q1",
        text="Q ?",
        idcc=None,
        idcc_name=None,
        fiches=[],
        code=[],
        idcc_chunks=[],
    )
    answer = Answer(
        generator="m", query_id="q1", status="ok", answer="R", prompt_sha256="s"
    )
    check = CitationCheck(
        quotes=4, verbatim=3, links=5, unknown_links=["https://x.test/a"]
    )
    summary, _, rows = build_report(
        "run", [context], [answer], [], citations={answer.item_id: check}
    )
    assert "## Citations" in summary
    assert "| m | 1 | 4 | 3 (75%) | 0 | 5 | 1 | 1 |" in summary
    assert rows[0]["links_not_in_prompt"] == "https://x.test/a"
