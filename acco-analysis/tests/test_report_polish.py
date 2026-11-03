import pytest

from acco_analysis import report_pdf, report_polish
from acco_analysis.report_polish import (
    MEANINGS,
    PolishError,
    build_user,
    check,
    parse_answer,
    placeholders,
    polish,
    split_template,
)

SOURCE = report_pdf.TEMPLATE.read_text()
PREAMBLE, PROSE = split_template(SOURCE)


def test_split_template_keeps_the_preamble_and_starts_at_the_outline():
    assert PROSE.startswith("#outline")
    assert PREAMBLE + PROSE == SOURCE
    assert "#let q(key)" in PREAMBLE


def test_every_placeholder_and_count_has_a_meaning():
    assert placeholders(PROSE) <= set(MEANINGS)
    assert set(report_pdf.COUNTS) <= set(MEANINGS)


def test_the_draft_passes_its_own_check():
    assert check(PROSE, PROSE) == []


def test_check_rejects_a_dropped_or_added_placeholder():
    assert any(
        "missing" in e for e in check(PROSE, PROSE.replace("#f.collected", "2399"))
    )
    assert any("added" in e for e in check(PROSE, PROSE + "\n#f.invented\n"))


def test_check_rejects_a_changed_quote_call():
    errors = check(PROSE, PROSE.replace('#q("same_day")', '#q("telework")', 1))
    assert any("#q calls differ" in e for e in errors)


def test_check_rejects_new_digits_and_forbidden_characters():
    assert any("digits" in e for e in check(PROSE, PROSE + "\nEn 1999.\n"))
    assert any("'$'" in e for e in check(PROSE, PROSE + "\nun $ ici\n"))


def test_check_rejects_a_changed_structure_and_a_too_long_text():
    assert any("headings" in e for e in check(PROSE, PROSE.replace("\n== ", "\n= ", 1)))
    assert any("#lead[" in e for e in check(PROSE, PROSE.replace("#lead[", "[", 1)))
    assert check(PROSE, PROSE.replace("\n\n#q(", "\n\n#lead[x]\n\n#q(", 1)) == []
    assert any("too long" in e for e in check(PROSE, PROSE + " mot" * 400))


def with_sentence(sentence):
    """The draft with one more sentence, before its final line."""
    return PROSE.replace(
        "= Réserves de lecture\n", f"= Réserves de lecture\n\n{sentence}\n", 1
    )


def test_check_rejects_words_that_make_the_text_stronger():
    errors = check(PROSE, with_sentence("L'accord est requis et uniquement appliqué."))
    assert any("requis" in e and "uniquement" in e for e in errors)
    # a word the draft already uses ("toujours", in "presque toujours") is allowed
    assert "toujours" in PROSE
    assert check(PROSE, with_sentence("Elle est toujours là.")) == []


def test_check_requires_the_first_and_last_lines_unchanged():
    errors = check(PROSE, PROSE.replace("#outline(title: [Sommaire]", "#outline(", 1))
    assert any("first line" in e for e in errors)
    errors = check(PROSE, PROSE.rstrip().rsplit("\n", 1)[0] + "\n")
    assert any("last line" in e for e in errors)


def sample_f():
    return {name: "7" for name in MEANINGS}


def sample_quotes():
    return {
        k: {"text": f"clause {k}", "company": "ACME", "year": "2021", "url": "u"}
        for k in report_pdf.QUOTE_KEYS
    }


def test_build_user_has_the_glossary_values_the_quotes_and_the_draft():
    user = build_user(PROSE, sample_f(), sample_quotes())
    assert "- #f.collected = 7 :" in user
    assert '#q("hours_canicule") : « clause hours_canicule » (ACME, 2021)' in user
    assert user.rstrip().endswith(PROSE.rstrip())


def test_build_user_refuses_a_placeholder_without_a_meaning():
    with pytest.raises(PolishError, match="no meaning"):
        build_user(PROSE + " #f.nope", sample_f(), sample_quotes())


def test_parse_answer_with_and_without_a_code_fence():
    typst, notes = parse_answer(
        "<<<TYPST\n```typst\n#outline()\ntexte\n```\nTYPST>>>\n<<<NOTES\nok\nNOTES>>>"
    )
    assert typst == "#outline()\ntexte\n" and notes == "ok"
    assert parse_answer("<<<TYPST\nA\nTYPST>>>") == ("A\n", "")
    with pytest.raises(PolishError):
        parse_answer("no block here")


class FakeChat:
    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def chat_text(self, system, user, *, max_tokens):
        self.requests.append(user)
        return self.answers.pop(0)


def good_answer():
    return f"<<<TYPST\n{PROSE}TYPST>>>\n<<<NOTES\n(a) rien\nNOTES>>>"


def test_polish_returns_the_checked_template_and_the_notes():
    chat = FakeChat([good_answer()])
    source, notes = polish(chat, SOURCE, sample_f(), sample_quotes())
    assert source == PREAMBLE + PROSE and "rien" in notes


def test_polish_sends_the_errors_back_and_accepts_the_second_answer():
    bad = "<<<TYPST\n" + PROSE.replace("#f.collected", "2399") + "TYPST>>>"
    chat = FakeChat([bad, good_answer()])
    source, _ = polish(chat, SOURCE, sample_f(), sample_quotes())
    assert source == SOURCE
    assert "rejetée" in chat.requests[1] and "#f.collected" in chat.requests[1]
    # the rejected answer travels back, to be corrected rather than redone
    assert "corrige uniquement" in chat.requests[1]
    assert "2399" in chat.requests[1]


def test_polish_raises_when_every_attempt_is_rejected():
    chat = FakeChat(["rien d'utile"] * report_polish.MAX_ATTEMPTS)
    with pytest.raises(PolishError, match="every attempt"):
        polish(chat, SOURCE, sample_f(), sample_quotes())
    assert len(chat.requests) == report_polish.MAX_ATTEMPTS
