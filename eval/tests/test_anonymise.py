import pytest

from retrieval_eval.anonymise import anonymise_regex


def test_regex_replaces_identifiers():
    out = anonymise_regex("Écrire à jean.d@exemple.fr ou au 06 12 34 56 78")
    assert out == "Écrire à EMAIL ou au TELEPHONE"


def test_siret_and_siren_are_told_apart():
    assert anonymise_regex("siret 123 456 789 00012") == "siret SIRET"
    assert anonymise_regex("siren 123456789") == "siren SIREN"


def test_spacy_replaces_people_and_keeps_acronyms():
    pytest.importorskip("spacy")
    pytest.importorskip("fr_core_news_md")
    from retrieval_eval.anonymise import anonymise

    out = anonymise("Monsieur Jean Martin du CSE m'a convoqué")
    assert "Martin" not in out and "CSE" in out


@pytest.fixture(scope="module")
def anon():
    pytest.importorskip("spacy")
    pytest.importorskip("fr_core_news_md")
    from retrieval_eval.anonymise import anonymise

    return anonymise


@pytest.mark.parametrize(
    "text",
    [
        "Mon CDD peut-il être rompu avant son terme ?",
        "Je saisis le CPH pour contester mon licenciement",
        "Liquidation judiciaire et licenciement économique : quels droits ?",
        "Que dit la Convention collective nationale des transports routiers ?",
        "Madame, Monsieur, bonjour",
        "Est-ce que j'ai droit à l'article L1224-1 du Code du travail ?",
        "JE SUIS A TEMPS PARTIEL ANNUALISE DANS LES SERVICES A LA PERSONNE",
        "Contrat Cesu et congés payés en janvier",
        "Mon employeur peut-il refuser mon CAP pâtisserie ?",
    ],
)
def test_legal_vocabulary_is_left_alone(anon, text):
    assert anon(text) == text


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        ("Monsieur LEGOUAS est marin", ["LEGOUAS"]),
        ("M. Carlier m'a convoqué", ["Carlier"]),
        ("Madame Ambre COUTURIER refuse mes congés", ["Ambre", "COUTURIER"]),
        ("J'ai subi des pressions chez LIDL par mes responsables", ["LIDL"]),
        ("Employeur EURONOR, je travaille à Boulogne", ["EURONOR", "Boulogne"]),
        ("Je travaille sur le port du Havre et l'entreprise déménage", ["Havre"]),
        ("Ma collègue Frédérique Medah a été licenciée", ["Medah", "Frédérique"]),
        ("Mon contrat avec Mediapost est-il valable ?", ["Mediapost"]),
    ],
)
def test_names_companies_and_towns_are_removed(anon, text, gone):
    out = anon(text)
    assert not any(g in out for g in gone), out


def test_placeholders_survive_the_name_rules(anon):
    out = anon("Appelez le 06 12 34 56 78 ou écrivez à jean@exemple.fr")
    assert out == "Appelez le TELEPHONE ou écrivez à EMAIL"


def test_geographic_regimes_that_matter_in_law_are_kept(anon):
    out = anon("Les jours fériés en Alsace-Moselle et en France")
    assert "Alsace-Moselle" in out and "France" in out
