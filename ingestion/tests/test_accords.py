import json
import unicodedata
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ingestion.contract import Chunk
from ingestion.pipeline import Inputs, chunk_source
from ingestion.snapshots.fetch import import_dir
from ingestion.snapshots.store import LocalStore
from ingestion.sources.accords import (
    TRUNCATION_THRESHOLD,
    _article_heading,
    _numbered_heading,
    normalise_agreement,
    split_sections,
    strip_toc,
)
from ingestion.text.office import OfficeError, extract_text


def _chunks(inputs: Inputs, agreement: int) -> list[Chunk]:
    id = f"ACCOTEXT00000000000{agreement}"
    return [
        c
        for c in chunk_source("accords_entreprise", inputs)
        if c.metadata.initial_id == id
    ]


def _text(chunk: Chunk) -> str:
    # the chunker leaves the body in NFKD, as for the other sources
    return unicodedata.normalize("NFC", chunk.content)


def _headers(chunks: list[Chunk]) -> list[str]:
    return [c.content.split("\n", 1)[0] for c in chunks]


def test_agreement_with_articles(inputs: Inputs):
    chunks = _chunks(inputs, 1)
    title = "accord relatif aux conditions de travail"
    assert _headers(chunks) == [
        title,
        f"{title} > TITRE 1 – DISPOSITIONS GÉNÉRALES > Article 1 – Objet",
        f"{title} > TITRE 1 – DISPOSITIONS GÉNÉRALES > Article 2 – Champ d'application",
        f"{title} > TITRE 2 – SANTÉ AU TRAVAIL > Article 3 – Fortes chaleurs",
        f"{title} > TITRE 2 – SANTÉ AU TRAVAIL > Article 4",
    ]
    # the table of contents is gone, with its page numbers
    text = "\n".join(c.content for c in chunks)
    assert "SOMMAIRE" not in text and "\t" not in text
    assert text.count("Fortes chaleurs") == 1

    heat = chunks[3]
    assert "plan national canicule" in heat.content
    # a sentence that starts with "Article 3" is not a heading
    assert "Article 3 du présent accord s'applique" in _text(heat)
    # a heading that starts a paragraph: the rest of the line is the text
    assert (
        _text(chunks[4])
        .split("\n", 1)[1]
        .startswith("Durée de l'accord. Le présent accord est conclu")
    )

    metadata = heat.metadata
    assert metadata.source == "accords_entreprise"
    # sections are numbered in the text, including the ones left out for lack of text
    assert metadata.id == "ACCOTEXT000000000001-5"
    assert metadata.initial_id == "ACCOTEXT000000000001"
    assert metadata.url == "https://www.legifrance.gouv.fr/acco/id/ACCOTEXT000000000001"
    assert (
        metadata.title == "EXEMPLE INDUSTRIE — accord relatif aux conditions de travail"
    )
    assert (metadata.idcc, metadata.idx) == ("1486", 0)
    assert metadata.company == "EXEMPLE INDUSTRIE"
    assert metadata.siret == "11111111100011"
    assert metadata.nature == "ACCORD"
    assert metadata.signature_date == "2024-06-04"
    assert metadata.themes == ["Santé et sécurité", "Durée du travail"]
    assert metadata.unions == ["CFDT"]


def test_agreement_with_numbered_headings(inputs: Inputs):
    chunks = _chunks(inputs, 2)
    assert _headers(chunks) == [
        "NAO 2023",
        "NAO 2023 > 1. Salaires > 1.1 Augmentation générale",
        "NAO 2023 > 1. Salaires > 1.2 Primes",
        "NAO 2023 > 2. Durée du travail",
        "NAO 2023 > 3. Dispositions finales",
    ]
    assert chunks[0].metadata.idcc is None
    assert chunks[0].metadata.unions == ["CGT", "CGT-FO"]
    assert chunks[0].metadata.nature == "AVENANT"


def test_agreement_without_structure(inputs: Inputs):
    (chunk,) = _chunks(inputs, 3)
    assert _text(chunk).startswith("compte rendu NAO\nCompte rendu de la réunion")
    # blanks to fill in are cut to one ellipsis (NFKD writes it as three dots)
    assert "...." not in chunk.content
    assert "Nom du salarié : ..." in _text(chunk)
    assert "vagues de chaleurs" in chunk.content
    # the idcc is not padded
    assert chunk.metadata.idcc == "16"


def test_strip_toc_block_and_page_numbers():
    lines = [
        "Préambule",
        "SOMMAIRE",
        "Article 1 – Objet\t2",
        "Article 2 – Durée ........ 3",
        "TITRE 2 – SANTÉ\tp 4",
        "",
        "Article 1 – Objet",
        "Le plafond est fixé à 12",
    ]
    assert strip_toc(lines) == [
        "Préambule",
        "Article 1 – Objet",
        "Le plafond est fixé à 12",
    ]


def test_strip_toc_without_marker_keeps_what_is_not_a_heading():
    lines = [
        "Article 5 – Primes\t12",
        "Prime de panier\t8",
        "Le seuil est de 35 heures par semaine\t35",
    ]
    # only the heading with its page number goes; table rows and sentences stay
    assert strip_toc(lines) == lines[1:]


@pytest.mark.parametrize(
    ("line", "level"),
    [
        ("Article 3 – Durée", 2),
        ("ARTICLE 12 bis : Prime", 2),
        ("Article 2.1. Objet", 2),
        ("· Article 2 : Dispositions locales", 2),
        ("Article premier", 2),
        ("Article IV - Dépôt", 2),
        ("TITRE II – SANTÉ", 1),
        ("Chapitre 2. Modes d'organisation", 1),
        ("Article 3 du présent accord s'applique", None),
        ("Articles 3 et 4", None),
        ("Article L. 3121-1 du code du travail", None),
        ("Section 2 du règlement", None),
        ("Le titre 2 prévoit", None),
    ],
)
def test_article_headings(line: str, level: int | None):
    heading = _article_heading(line)
    assert (heading.level if heading else None) == level


@pytest.mark.parametrize(
    ("line", "level"),
    [
        ("1. Salaires", 1),
        ("1.1 Durée du travail", 2),
        ("2.3. Compteurs", 2),
        ("II. Propositions initiales", 1),
        ("12.03.2020 Réunion", None),
        ("35 heures par semaine", None),
        ("1. Les salariés seront payés,", None),
    ],
)
def test_numbered_headings(line: str, level: int | None):
    heading = _numbered_heading(line)
    assert (heading.level if heading else None) == level


def test_long_heading_line_keeps_its_text_as_the_body():
    text = "\n".join(
        ["Article 1 – Objet", "a", "Article 2 – Durée", "b"]
        + ["Article 3 : " + "texte " * 40]
        + ["Article 4 – Fin", "c"]
    )
    sections = split_sections(text)
    assert [s.breadcrumb for s in sections][3] == ["Article 3"]
    assert sections[3].lines[0].startswith("texte texte")


def test_few_headings_give_a_single_section():
    (section,) = split_sections("Article 1 – Objet\nTexte\nArticle 2 – Fin\nTexte")
    assert section.breadcrumb == []
    assert len(section.lines) == 4


def _docx(path: Path, paragraphs: list[str]) -> Path:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>',
        )
    return path


def _agreement(content: str) -> dict:
    return {
        "acco": {
            "id": "ACCOTEXT000000000009",
            "data": "UEsDBBQ=",
            "attachment": {"content": content},
        }
    }


def test_normalise_drops_the_base64_file():
    agreement = normalise_agreement(_agreement("Court."), Path("/nowhere"))
    assert "data" not in agreement["acco"]
    assert agreement["acco"]["attachment"] == {
        "content": "Court.",
        "content_source": "api",
    }


def test_normalise_reads_a_cut_text_from_the_original(tmp_path: Path):
    cut = "x" * TRUNCATION_THRESHOLD
    _docx(tmp_path / "ACCOTEXT000000000009.docx", ["Début", cut, "Fin du texte"])
    attachment = normalise_agreement(_agreement(cut), tmp_path)["acco"]["attachment"]
    assert attachment["content_source"] == "docx"
    assert attachment["content"] == f"Début\n{cut}\nFin du texte"


def test_normalise_keeps_a_long_text_the_original_does_not_extend(tmp_path: Path):
    text = "x" * TRUNCATION_THRESHOLD
    _docx(tmp_path / "ACCOTEXT000000000009.docx", ["court"])
    attachment = normalise_agreement(_agreement(text), tmp_path)["acco"]["attachment"]
    assert (attachment["content_source"], attachment["content"]) == ("api", text)


def test_normalise_flags_a_cut_text_without_original(tmp_path: Path):
    text = "x" * TRUNCATION_THRESHOLD
    attachment = normalise_agreement(_agreement(text), tmp_path)["acco"]["attachment"]
    assert attachment["content_source"] == "api-truncated"
    (tmp_path / "ACCOTEXT000000000009.docx").write_bytes(b"not a zip")
    attachment = normalise_agreement(_agreement(text), tmp_path)["acco"]["attachment"]
    assert attachment["content_source"] == "api-truncated"


def test_extract_docx_tabs_and_breaks(tmp_path: Path):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    document = (
        f'<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>A</w:t><w:tab/>'
        "<w:t>B</w:t><w:br/><w:t>C</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>D</w:t></w:r></w:p></w:body></w:document>"
    )
    path = tmp_path / "a.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
    assert extract_text(path) == "A\tB\nC\nD"


def test_extract_odt(tmp_path: Path):
    ns = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    content = (
        f'<office:document-content xmlns:text="{ns}" xmlns:office="urn:o">'
        "<office:body><office:text>"
        "<text:h>Titre</text:h>"
        '<text:p>un<text:s text:c="2"/>deux<text:tab/>'
        "<text:span>trois</text:span></text:p>"
        "</office:text></office:body></office:document-content>"
    )
    path = tmp_path / "a.odt"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", content)
    assert extract_text(path) == "Titre\nun  deux\ttrois"


def test_extract_refuses_what_it_cannot_read(tmp_path: Path):
    (tmp_path / "a.docx").write_bytes(b"not a zip")
    with pytest.raises(OfficeError):
        extract_text(tmp_path / "a.docx")
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    with pytest.raises(OfficeError, match="unsupported"):
        extract_text(tmp_path / "a.pdf")


def _results(root: Path) -> Path:
    """What legifrance_acco.py writes: results/accords/<id>.json|docx and
    results/ids.json."""
    accords = root / "results" / "accords"
    accords.mkdir(parents=True)
    (root / "results" / "ids.json").write_text(
        json.dumps(
            {
                "query": {"keywords": ["canicule"]},
                "searched_at": "2026-10-28T10:13:49+00:00",
            }
        )
    )
    cut = "x" * TRUNCATION_THRESHOLD
    for number, content in ((1, "Texte court."), (2, cut)):
        id = f"ACCOTEXT00000000000{number}"
        agreement = _agreement(content)
        agreement["acco"]["id"] = id
        (accords / f"{id}.json").write_text(json.dumps(agreement))
        _docx(accords / f"{id}.docx", ["Texte complet", cut])
    (accords / "notes.json").write_text("{}")
    return accords


def test_import_acco_dir(tmp_path: Path):
    store = LocalStore(tmp_path / "store")
    accords = _results(tmp_path)
    now = datetime(2026, 10, 28, tzinfo=UTC)

    manifest = import_dir(store, "acco", accords, now=now)
    assert manifest is not None
    assert manifest.snapshot_id.startswith("20261028-local.")
    assert manifest.paths() == [
        "ACCOTEXT000000000001.json",
        "ACCOTEXT000000000002.json",
    ]
    assert manifest.upstream["fond"] == "ACCO"
    assert manifest.upstream["search"] == {
        "query": {"keywords": ["canicule"]},
        "searched_at": "2026-10-28T10:13:49+00:00",
    }
    assert manifest.upstream["text_sources"] == {"api": 1, "docx": 1}

    stored = json.loads(
        store.fetch_file(manifest, "ACCOTEXT000000000002.json").read_text()
    )
    assert "data" not in stored["acco"]
    assert stored["acco"]["attachment"]["content"].startswith("Texte complet\n")

    # same content: nothing new
    assert import_dir(store, "acco", accords, now=now) is None


def test_import_acco_dir_without_agreements(tmp_path: Path):
    (tmp_path / "accords").mkdir()
    (tmp_path / "accords" / "KALICONT000000000001.json").write_text("{}")
    with pytest.raises(RuntimeError, match="No acco data file"):
        import_dir(LocalStore(tmp_path / "store"), "acco", tmp_path / "accords")
