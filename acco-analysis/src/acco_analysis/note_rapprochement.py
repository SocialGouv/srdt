"""A note that sets this analysis beside another study (the DS2/DS1 note on adaptation
to climate change in company agreements) and explains where they agree and why they
seem to differ.

Same machinery as the report: prose in `note_rapprochement.typ`, figures computed and
formatted in Python (`build_data`), the French polished by the model with the figures
untouched (`report_polish.polish`, with this note's own prompt and glossary).
"""

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from acco_analysis.report_pdf import fr_int, fr_pct
from acco_analysis.report_polish import STYLE_GUIDE

TEMPLATE = Path(__file__).with_name("note_rapprochement.typ")
START = "// prose"  # the first line of the prose; what precedes it is kept as is

SYSTEM = (
    """# Task

You are a senior French-language editor and analyst. Rewrite the French prose of a short internal note so that it reads as natural, precise, well-constructed professional French, WITHOUT changing what it claims. The draft was written by a model that is not good at French; the analysis is checked, the wording is not.

## Context (what the note is)

- Our team analysed heat clauses in French company collective agreements (2,399 agreements signed 2017-2026, collected on heat-related terms; two language models coded each clause).
- Another administrative unit wrote a note, "DS2/DS1" (31 August 2026), on adaptation to climate change in company and branch agreements (72 texts, then 459 heat texts signed since 2025 of which 40 sampled; plus a branch-level section).
- This note compares the two: where they converge, where they seem to differ, and how to read each gap. Audience: colleagues who will cite both documents. Sober, factual, no taking sides: it never says which note is right, only what each counts and why figures differ.
- Length: about 2 pages. Do not make it longer.

## Input and output

INPUT (the user message): a glossary of the `#f.` placeholders (name, current value, meaning) and the draft in Typst markup.

OUTPUT, in this order, and nothing else:
<<<TYPST
the complete revised Typst prose, from the line `// prose` to the final `#context` line
TYPST>>>
<<<NOTES
in French, three short lists: (a) sentences whose meaning you changed on purpose and why; (b) the three claims you find most exposed or hardest to support, even if you left them unchanged ("none" is not acceptable); (c) any placeholder you could not place.
NOTES>>>

## Hard constraints (checked by a script; a violation means the answer is rejected)

1. Keep EVERY `#f.<name>` placeholder from the draft, and add none. Each must still be used at least once, in a sentence where it still states the same figure.
2. No hard-coded figure, percentage, count, year or name may be added. Every figure of the other note (72, 459, 40, 33 %, 22 %, 38 %, 17 %, the dates, the decree number, "neuf branches", IDCC 7018) is quoted exactly as in the draft and attributed to the note DS2/DS1: do not change, round or reattribute any of them.
3. Placeholder values change when the data is refreshed: every sentence must stay correct and grammatical for any value of 2 or more. Do not add quantifiers next to a placeholder ("la majorité", "une minorité", "seulement"...).
4. Keep the section structure: same headings, same order, same levels (`=`). You may reword a heading. Keep the table exactly as it is (columns, rows, cells), and the first line (`// prose`) and the last line (`#context [...]`) exactly.
5. Typst syntax: `*gras*`, lists with `-`. Use `~` for a non-breaking space before `:` `;` `?` `!` and `%` and between a number and its unit. Do not use `#` except for the existing placeholders, the table and the last line. Do not use `$`, `@`, backticks or HTML.

## Rules about the content

- You may reformulate, merge or split sentences, reorder inside a section, and cut redundancy. You may NOT add a fact, an example, a cause, a recommendation or a judgement that is not in the draft or the glossary.
- Never make a sentence stronger. Keep every hedge ("au moins", "ne se superposent pas", "nous ne connaissons pas"). Do not say that a note is wrong, or that a difference proves anything.
- Keep each figure attached to its own scope: the whole corpus (2017-2026) versus the agreements signed since 2025, and the period covered by the note DS2/DS1 (signed 2023-2026). Never merge two figures of different scopes into one sentence, and never drop a period.
- Keep the attribution clear in each sentence: what the note DS2/DS1 says, what our analysis says.
- Keep the four apparent gaps and the closing advice for citing both texts.

"""
    + STYLE_GUIDE
    + """## Before you answer, check

- Every `#f.` name of the draft is present, none added; the table is untouched.
- No new digit; every figure of the other note unchanged and attributed to it.
- No sentence stronger than the draft; no verdict on which note is right.
- Each sentence still true if a placeholder is any number from 2 to 5,000.
- `~` in the right places; no stray `#`, `$` or `@`.
"""
)

MEANINGS: dict[str, str] = {
    "collected": "accords d'entreprise collectés (tous)",
    "years": "période de signature des accords collectés",
    "heat_loose": "accords contenant une clause chaleur (au moins un des deux modèles)",
    "heat_strict": "accords contenant une clause chaleur (les deux modèles)",
    "companies": "entreprises distinctes derrière ces accords (numéro SIREN)",
    "recent_collected": "accords collectés signés depuis 2025",
    "recent_heat_loose": "parmi eux, accords avec une clause chaleur (au moins un des deux modèles)",
    "recent_n": "accords signés depuis 2025 avec une clause chaleur (les deux modèles)",
    "ded_n": "parmi eux, accords avec un dispositif propre à la chaleur",
    "recent_generic": "accords signés depuis 2025 où la chaleur n'est qu'un cas d'une clause générale",
    "recent_generic_share": "part de ces accords parmi ceux signés depuis 2025 avec une clause chaleur",
    "recent_schedule_share": "part des accords récents qui adaptent les horaires",
    "ded_schedule_share": "part des accords récents à dispositif dédié qui adaptent les horaires",
    "recent_cooling_share": "part des accords récents qui prévoient un rafraîchissement",
    "ded_cooling_share": "part des accords récents à dispositif dédié qui prévoient un rafraîchissement",
    "recent_graded_share": "part des accords récents dont le déclencheur est un niveau de vigilance ou un seuil de température",
    "ded_graded_share": "même part, parmi les accords récents à dispositif dédié",
    "recent_telework_share": "part des accords récents qui prévoient le télétravail",
    "ded_telework_share": "part des accords récents à dispositif dédié qui prévoient le télétravail",
    "recent_pay_maintained_share": "part des accords récents qui maintiennent la rémunération",
    "ded_pay_maintained_share": "part des accords récents à dispositif dédié qui maintiennent la rémunération",
    "recent_pay_maintained": "nombre d'accords récents qui maintiennent la rémunération",
    "recent_pay_unspecified_share": "part des accords récents muets sur l'effet sur la rémunération",
    "decree": "accords citant le décret n° 2025-482 (recherche de mots-clés), tous signés confondus",
    "recent_decree": "parmi eux, accords signés depuis 2025",
    "recent_decree_share": "part des accords signés depuis 2025 avec une clause chaleur qui citent le décret",
    "land": "accords du paysage (services d'aménagement paysager)",
    "land_template": "parmi eux, accords reprenant une clause type partagée avec une autre entreprise",
}


def build_data(
    report_f: Mapping[str, str], facts: Mapping[str, int], snapshot: str
) -> dict[str, Any]:
    """The figures of the note: some are those of the report (`report_f`, formatted), the
    others are shares of the recent agreements computed here."""
    recent, ded = facts["recent_n"], facts["ded_n"]

    def share(count: str, of: int) -> str:
        return fr_pct(facts[count] / of)

    f = {
        name: report_f[name]
        for name in (
            "collected",
            "years",
            "heat_loose",
            "heat_strict",
            "decree",
            "land",
            "land_template",
        )
    }
    for measure in ("schedule", "cooling", "graded", "telework", "pay_maintained"):
        f[f"recent_{measure}_share"] = share(f"recent_{measure}", recent)
        f[f"ded_{measure}_share"] = share(f"ded_{measure}", ded)
    f |= {
        "companies": fr_int(facts["companies"]),
        "recent_collected": fr_int(facts["recent_collected"]),
        "recent_heat_loose": fr_int(facts["recent_heat_loose"]),
        "recent_n": fr_int(recent),
        "ded_n": fr_int(ded),
        "recent_generic": fr_int(recent - ded),
        "recent_generic_share": fr_pct((recent - ded) / recent),
        "recent_pay_maintained": fr_int(facts["recent_pay_maintained"]),
        "recent_pay_unspecified_share": share("recent_pay_unspecified", recent),
        "recent_decree": fr_int(facts["recent_decree"]),
        "recent_decree_share": share("recent_decree", recent),
    }
    return {"snapshot": snapshot, "generated": date.today().isoformat(), "f": f}
