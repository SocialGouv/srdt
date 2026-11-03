import shutil

import pytest

from acco_analysis import note_rapprochement as note
from acco_analysis import report_pdf
from acco_analysis.report_polish import check, placeholders, split_template

SOURCE = note.TEMPLATE.read_text()
PREAMBLE, PROSE = split_template(SOURCE, note.START)

REPORT_F = {
    k: "1"
    for k in (
        "collected",
        "years",
        "heat_loose",
        "heat_strict",
        "decree",
        "land",
        "land_template",
    )
}
FACTS = {
    "recent_n": 400,
    "ded_n": 300,
    "recent_collected": 500,
    "recent_heat_loose": 450,
    "companies": 1300,
    "recent_pay_maintained": 10,
    "recent_pay_unspecified": 360,
    "recent_decree": 20,
} | {
    f"{prefix}_{m}": 40
    for prefix in ("recent", "ded")
    for m in ("schedule", "cooling", "graded", "telework", "pay_maintained")
}


def test_every_placeholder_of_the_template_has_a_meaning_and_a_value():
    data = note.build_data(REPORT_F, FACTS, "s1")
    used = placeholders(PROSE)
    assert used <= set(note.MEANINGS)
    assert used <= set(data["f"])


def test_template_prose_starts_at_the_marker_and_passes_its_own_check():
    assert PROSE.startswith(note.START) and "#let" not in PROSE
    assert check(PROSE, PROSE) == []


def test_build_data_shares_are_of_the_recent_agreements_or_the_dedicated_ones():
    f = note.build_data(REPORT_F, FACTS, "s1")["f"]
    assert f["recent_schedule_share"] == f"10{report_pdf.NBSP}%"  # 40 of 400
    assert f["ded_schedule_share"] == f"13{report_pdf.NBSP}%"  # 40 of 300
    assert f["recent_generic"] == "100"  # 400 - 300
    assert f["recent_generic_share"] == f"25{report_pdf.NBSP}%"
    assert f["recent_pay_unspecified_share"] == f"90{report_pdf.NBSP}%"
    assert f["recent_decree_share"] == f"5{report_pdf.NBSP}%"
    assert f["companies"] == f"1{report_pdf.NARROW}300"


def test_system_prompt_carries_the_shared_style_guide_and_its_own_rules():
    assert "## French style guide" in note.SYSTEM
    assert "// prose" in note.SYSTEM and "DS2/DS1" in note.SYSTEM


@pytest.mark.skipif(shutil.which("typst") is None, reason="typst not installed")
def test_template_compiles_to_a_pdf(tmp_path):
    data = note.build_data(REPORT_F, FACTS, "s1")
    pdf = tmp_path / "note.pdf"
    pages = report_pdf.render(data, tmp_path / "work", pdf, template=note.TEMPLATE)
    assert pdf.read_bytes().startswith(b"%PDF")
    assert 1 <= pages <= 6
