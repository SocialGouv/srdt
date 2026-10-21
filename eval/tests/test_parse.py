import pytest

from judge_eval.judge import ParseError, parse_verdict


@pytest.mark.parametrize(
    ("text", "label", "reasoning"),
    [
        ('{"reasoning": "ok", "verdict": "Oui"}', True, "ok"),
        ('{"reasoning": "ko", "verdict": "Non"}', False, "ko"),
        # casing, accents, punctuation, other languages, booleans
        ('{"reasoning": "", "verdict": "oui"}', True, ""),
        ('{"reasoning": "", "verdict": " NON. "}', False, ""),
        ('{"reasoning": "", "verdict": "yes"}', True, ""),
        ('{"reasoning": "", "verdict": false}', False, ""),
        # key order and missing reasoning
        ('{"verdict": "Non", "reasoning": "x"}', False, "x"),
        ('{"verdict": "Oui"}', True, ""),
        # code fence and surrounding prose
        ('```json\n{"reasoning": "r", "verdict": "Non"}\n```', False, "r"),
        ('Voici ma réponse : {"reasoning": "r", "verdict": "Oui"} Merci.', True, "r"),
        # reasoning models
        (
            '<think>Hmm {"verdict": "Non"}</think>{"reasoning":"r","verdict":"Oui"}',
            True,
            "r",
        ),
        # braces inside the reasoning text
        (
            '{"reasoning": "règle {art. L1225}", "verdict": "Non"}',
            False,
            "règle {art. L1225}",
        ),
    ],
)
def test_parses_valid_replies(text, label, reasoning):
    parsed = parse_verdict(text)
    assert parsed.verdict is label
    assert parsed.reasoning == reasoning


def test_truncated_json_is_recovered_when_the_verdict_came_first():
    cut = '{"verdict": "Non", "reasoning": "La réponse ne mentionne pas le délai de'
    assert parse_verdict(cut).verdict is False


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Oui",  # free text is never turned into a verdict
        "Non, la réponse est incorrecte.",
        '{"reasoning": "r"}',  # no verdict
        '{"reasoning": "r", "verdict": "Peut-être"}',
        # truncated before the verdict
        '{"reasoning": "Le salarié a droit à un préavis qui',
        "<think>réflexion sans fin",
    ],
)
def test_unusable_replies_raise(text):
    with pytest.raises(ParseError):
        parse_verdict(text)
