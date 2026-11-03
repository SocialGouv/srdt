"""Stage 12b: have an LLM (Albert) improve the French of the report's prose.

The model rewrites the prose of `report.typ` only. The figures (`#f.<name>`) and the
quoted clauses (`#q("<key>")`) must come back untouched: `check` verifies it, and a
rejected answer is sent back with the errors. The result is written next to the report
in `out/`, never over `report.typ`.
"""

import re
from collections.abc import Mapping
from typing import Protocol

MAX_ATTEMPTS = 4
MAX_GROWTH = 1.15  # the polished prose may be at most 15 % longer than the draft
MAX_TOKENS = 8000
START = "#outline"  # the prose starts at this line, the preamble before it is kept

SYSTEM = """# Task

You are a senior French-language editor and analyst. Rewrite the French prose of a short \
internal analysis note so that it reads as natural, precise, well-constructed professional \
French, WITHOUT changing what it claims. The draft was written by a model that is not good \
at French; the analysis behind it is sound and checked, the wording is not.

## Context (what the note is)

- Corpus: 2,399 French company collective agreements ("accords d'entreprise", from \
Légifrance, signed 2017-2026), collected on heat-related search terms. Of these, 2,064 \
contain a clause that names heat (canicule, fortes chaleurs...).
- Two language models read and coded every extract. "Strict" = the two models agree. The \
counting unit is always the agreement ("accord"), never the extract. Figures in the note \
use the strict reading unless stated.
- The note is NOT a dashboard. Its purpose is to explain what the clauses MEAN: how heat \
appears (a dedicated scheme, or one case in a general clause), what triggers a scheme and \
what it provides, how heat is used to loosen rules (same-day planning, recovery of lost \
hours, rest derogations, exceptional telework), who decides, how binding it is, who pays, \
and what the clauses leave unsaid. Figures only support a claim.
- Audience: the internal analysis team (employment-law-literate, not necessarily data \
people). It is not published and not legal advice. Length: 3 pages, about 1,550 words of \
prose. Do not make it longer.

## Input and output

INPUT (the user message): a glossary of the `#f.` placeholders (name, meaning, current \
value), the quoted clauses (read-only) and the draft prose in Typst markup.

OUTPUT, in this order, and nothing else:
<<<TYPST
the complete revised Typst prose, from the line `#outline` to the final `#context` line
TYPST>>>
<<<NOTES
in French, three short lists: (a) sentences whose meaning you changed on purpose and why; \
(b) claims you think the draft states too strongly or cannot support, with a more cautious \
wording you would accept (do NOT apply it in the Typst block unless it is strictly more \
cautious than the draft). In (b) always list at least the three claims you find most \
exposed, even if you leave them unchanged; "none" is not an acceptable answer; (c) any \
placeholder you could not place.
NOTES>>>

## Hard constraints (checked by a script; a violation means the answer is rejected)

1. Keep EVERY `#f.<name>` placeholder and EVERY `#q("<key>")` call from the draft, and add \
none. Each placeholder must still be used at least once, in a sentence where it still \
states the same figure. You may move a placeholder inside its sentence or section.
2. No hard-coded figure, percentage, count, year or company name may be added. The only \
digits allowed in the prose are those already in the draft ("décret n° 2025-482 du 27 mai \
2025", "1er juin", "15 septembre", "6~h", "7~h", "30~°C", "28~°C", ...), and the section \
numbers produced by Typst.
3. Placeholder values change when the data is refreshed. Every sentence must stay correct \
and grammatical for any value of 2 or more (and "withdrawal", which already carries its \
noun and may be "1 accord" or "N accords"). Do not write "ces deux accords", "le seul \
accord", "la majorité" or "une minorité" next to a placeholder, because that depends on \
the value. Words like "souvent", "plusieurs", "presque toujours" are allowed only where \
the draft already has them; do not add new quantifiers.
4. Keep the section structure: same headings, same order, same levels (`=` and `==`). You \
may reword a heading. Do not add or remove sections or bullets of substance.
5. Keep each `#q("key")` as its own paragraph after the paragraph that introduces it, and \
keep the `#lead[ ... ]` wrapper around those introducing paragraphs (you may use it on others). A quote is shown \
automatically with its company, year and link: never retype or alter a quote.
6. Keep the first line (`#outline(...)`) and the last line (`#context [...]`) exactly as \
they are.
7. Typst syntax: `*gras*`, `_italique_`, lists with `-` or `+`. Use `~` for a non-breaking \
space: before `:` `;` `?` `!` and `%`, inside « ~ », and between a number and its unit \
(30~°C, 6~h). The placeholders that print percentages already contain the non-breaking \
space. Do not use `#` except for the existing placeholders and calls. Do not use `$`, `@`, \
backticks or HTML.

## Rules about the content (do not break the analysis)

- You may reformulate, merge or split sentences, reorder inside a section, and cut \
redundancy. You may NOT add a fact, an example, a number, a legal reference, a cause or a \
recommendation that is not in the draft or in the glossary.
- Never make a sentence stronger: do not turn "est prévu" into "est requis" or "impose", \
do not say at which level, step or case a measure applies unless the draft says so, do not \
add words such as "toujours", "jamais", "tous", "seul", "uniquement", "systématique", \
"majorité". If a hedge exists ("parfois", "plusieurs", "dans les \
extraits lus", "le corpus ne permet pas de dire"), keep it or make it more cautious.
- Do not turn description into explanation. The draft deliberately does NOT claim that the \
2025 decree explains the trends, that Covid explains the telework peak, that the clauses \
are applied, or that the figures describe French companies in general. Keep it so.
- Do not generalise from a quoted clause to all clauses. A quote illustrates; the figure \
next to it states the extent.
- Keep the distinction between "accords" (counted) and "extraits" (what was read). Counts \
with "strict" mean both models agree; keep that explained once, in "Ce qui a été lu".
- Keep the reservations section: it is a deliverable, not filler.

## French style guide

- Register: internal analysis note. Sober, precise, direct. Active voice, subject first. \
Average sentence under 25 words; no chains of more than two subordinate clauses. No \
marketing tone, no rhetorical questions, no exclamation marks, no emojis.
- Vary sentence openings (the draft repeats "Dans ... Dans ..."). Prefer concrete verbs \
over "il y a", "il existe", "permettre de". Avoid anglicisms and calques; "plancher" \
(lower bound), "ordre de grandeur", "délai de prévenance" are fine and intended.
- Use the legal vocabulary of French employment law correctly: accord d'entreprise, \
clause, délai de prévenance, durée maximale quotidienne, repos quotidien, annualisation du \
temps de travail, activité partielle, CSE, DUERP (document unique d'évaluation des \
risques), vigilance Météo-France (jaune, orange, rouge), intempéries, force majeure, \
circonstances exceptionnelles, télétravail, droit de retrait. Spell out an acronym at \
first use only if the draft does.
- Terminology to keep: "accord" for agreement, "clause", "extrait" for what was read, \
"lecture stricte / large", "les deux modèles". Never "saveurs"; the word "nuances" is not \
used in this note.
- Typography: guillemets « » (with non-breaking spaces), "1er", "n°", "30 °C", lists with \
parallel structure, bold only for the lead phrase of a paragraph or bullet as in the draft.
- Numbers: the placeholders are already formatted (narrow no-break space as thousands \
separator, decimal comma). Do not re-format them. Agree nouns correctly after them.
- Titles: short, informative, no colon-heavy slogans.
- Read each paragraph as a French reader would: remove stiffness (nominalisations, "au \
niveau de", "dans le cadre de" when unnecessary), keep it flowing and unambiguous.

## What each part must keep saying (the analysis, in one line each)

1. "L'essentiel": five findings, in this order: heat is rarely treated for itself (a \
dedicated scheme vs a case in a general "intempéries"/"circonstances exceptionnelles" \
clause; the two logics call for different measures (dedicated schemes work first on the \
schedule; general clauses mobilise telework and same-day planning); the trigger is often \
vague; the employer decides and pay is almost never said; heat also serves to loosen rules.
2. "Ce qui a été lu": two models, agreement as unit, strict reading, floors not \
prevalence, the corpus describes companies that frame heat, not French companies.
3. "Deux manières de parler de la chaleur": dedicated scheme (example quote), and heat as \
one word in a list that triggers a rule written for all hazards; many of these are \
template clauses copied from one agreement to others, so the number of distinct drafting \
choices is much lower than the number of agreements.
4. "Les secteurs représentés": the corpus comes unevenly from almost all broad sectors (industry \
first), and the shares reflect what was collected, not the economy; the sector orients how heat \
is treated (industry, transport and construction write dedicated schemes; public administration \
and office activities treat heat as one exceptional event, with telework); landscaping is an \
exception, with template annualisation clauses that treat heat as bad weather (same-day planning \
change, collective interruption with recovery), which explains most of those measures.
5. "Les dispositifs propres à la chaleur": the trigger is the weak point (heat undefined \
in many); when defined, three ways: temperature threshold (30 and 28 °C most cited, some \
thresholds are composite and name the measuring source), Météo-France vigilance level \
(delegates the definition to a third party), fixed period (summer hours 1 June-15 \
September); the 2025 decree and the agreements that adopt its vigilance vocabulary. Then \
what schemes provide: schedule first (continuous day, start at 6 or 7 h, summer hours), \
then cheap material measures, then organisation (information, risk assessment via the \
DUERP, CSE opinion); the most graduated plans escalate by vigilance level; the heaviest \
measures (premium, stopping activity) are the rarest, and a stop can be decided after the \
fact (example).
6. "Quand la chaleur assouplit les règles": heat as a ground to loosen: same-day planning \
change in annualisation clauses; making up lost hours (collective interruption nearly \
always comes with recovery; recovery noted as unpaid in some agreements); derogation from \
rest or maximum daily hours where heat is an activity peak, not a risk; telework as a \
response to "exceptional circumstances" where heat is one cause among others and the \
management alone judges. Then the trend sentence, which describes the collected corpus \
and explicitly does not explain it.
7. "Qui décide, avec quelle force, à quel prix": initiative (employer far ahead; employee \
request and agreement with representatives are marginal; many unspecified; models \
disagree on many), force (faculty vs obligation vs principle; models disagree on many), \
procedure guarantees are minority, pay mostly silent and when said mostly "hours to make \
up"; the closing quote shows compensation as exceptional and discretionary.
8. "Ce que les clauses ne disent pas": when heat starts, what to do when measures are not \
enough (the right to withdraw is cited in very few extracts; that is a statement about \
the extracts read, not about the agreements), who is protected, and whether any of it is \
applied (the analysis covers texts only).
9. "Réserves de lecture": floors; no coding validated by hand, initiative and force among \
the least reliable codes; keyword searches are not codings; template clauses; quotes \
checked word for word; the trend shares are over collected agreements and the last year \
is partial.

## Before you answer, check

- Every `#f.` name and every `#q("...")` of the draft is present, none added.
- No new digit in the prose beyond those of the draft.
- No sentence stronger than the draft; no new cause, example or recommendation.
- Each sentence still true if a placeholder is any number from 2 to 5,000.
- `~` in the right places; no stray `#`, `$` or `@`.
- The text fits roughly 3 pages (no more than about 1,550 words).
"""

# the French style guide, shared with the other notes that are polished the same way
STYLE_GUIDE = SYSTEM[
    SYSTEM.index("## French style guide") : SYSTEM.index("## What each part must keep")
]

# what each `#f.<name>` of the template counts, for the model (and the reader of a prompt)
MEANINGS: dict[str, str] = {
    "schedule_shift": "accords dont la clause décale ou aménage les horaires (lecture stricte)",
    "sec_c": "accords de l'industrie manufacturière (parmi ceux avec une clause chaleur, lecture stricte)",
    "sec_c_share": "part de l'industrie manufacturière parmi ces accords",
    "sec_n_share": "part des services administratifs et de soutien (dont le paysage)",
    "sec_o_share": "part de l'administration publique, sécurité sociale comprise",
    "sec_h_share": "part des transports et de l'entreposage",
    "sec_f_share": "part de la construction",
    "sec_c_dedicated": "part des accords de l'industrie avec un dispositif dédié à la chaleur",
    "sec_h_dedicated": "part des accords des transports et de l'entreposage avec un dispositif dédié",
    "sec_f_dedicated": "part des accords de la construction avec un dispositif dédié",
    "sec_o_dedicated": "part des accords de l'administration publique avec un dispositif dédié",
    "sec_o_telework": "part des accords de l'administration publique qui prévoient le télétravail",
    "prime_industry_share": "part des accords prévoyant une prime qui sont de l'industrie",
    "rest_industry_share": "part des accords prévoyant une dérogation au repos qui sont de l'industrie",
    "land": "accords du paysage (services d'aménagement paysager)",
    "land_idcc": "parmi eux, accords relevant de la convention collective de branche du paysage (IDCC 7018)",
    "land_template": "parmi eux, accords reprenant une clause type partagée avec une autre entreprise",
    "land_same_day": "accords du paysage permettant de modifier le planning le jour même",
    "land_collective": "accords du paysage prévoyant une interruption collective du travail (assortie d'une récupération)",
    "land_same_day_share": "part du paysage dans les accords permettant de modifier le planning le jour même",
    "collective_total": "accords prévoyant une interruption collective du travail, tous secteurs",
    "other_collective": "accords hors paysage prévoyant une interruption collective",
    "other_same_day": "accords hors paysage permettant de modifier le planning le jour même",
    "no_ape": "accords sans code APE exploitable, non classés par secteur",
    "specific_schedule": "accords à dispositif dédié dont un extrait propre à la chaleur décale ou aménage les horaires",
    "generic_telework": "accords dont un extrait où la chaleur n'est qu'un cas d'une règle générale prévoit le télétravail",
    "generic_same_day": "accords dont un extrait où la chaleur n'est qu'un cas d'une règle générale permet de modifier les horaires le jour même",
    "summer_hours": "accords avec des horaires d'été fixes",
    "water": "accords prévoyant l'eau (mise à disposition)",
    "cooling": "accords prévoyant un rafraîchissement (ventilateurs, climatisation...)",
    "extra_breaks": "accords prévoyant des pauses supplémentaires",
    "protective_gear": "accords prévoyant un équipement ou une tenue de protection",
    "prevention_info": "accords prévoyant information ou sensibilisation",
    "risk_assessment": "accords prévoyant un diagnostic ou une évaluation des risques",
    "prime": "accords prévoyant une prime ou indemnité",
    "same_day_change": "accords permettant de modifier les horaires le jour même",
    "rest_derogation": "accords prévoyant une dérogation au repos ou à la durée maximale",
    "collective_stoppage": "accords prévoyant une interruption collective du travail",
    "collective_stoppage_recovery": "parmi eux, accords où l'interruption collective s'accompagne d'une récupération des heures",
    "production_stop": "accords prévoyant l'arrêt ou la suspension de l'activité",
    "health_follow_up": "accords prévoyant un suivi médical ou de santé",
    "canicule_unqualified": "accords dont le déclencheur est « canicule » ou « fortes chaleurs » sans précision",
    "temperature_threshold": "accords dont le déclencheur est un seuil de température",
    "fixed_period": "accords dont le déclencheur est une période fixe",
    "vigilance_yellow": "accords déclenchés par la vigilance Météo-France jaune",
    "vigilance_orange": "accords déclenchés par la vigilance Météo-France orange",
    "vigilance_red": "accords déclenchés par la vigilance Météo-France rouge",
    "employer_decision": "accords dont le déclencheur est la décision de l'employeur",
    "init_employer": "accords où l'employeur déclenche ou décide",
    "init_employee": "accords où la mesure est accordée à la demande du salarié",
    "init_reps": "accords où la mesure suppose l'accord des représentants du personnel",
    "init_unspecified": "accords qui ne disent pas qui décide",
    "init_disagree": "accords où les deux modèles divergent sur l'initiative",
    "faculty": "accords dont la clause est une simple faculté (« pourra », « peut »)",
    "obligation": "accords dont la clause est une obligation",
    "principle": "accords dont la clause est un principe ou un objectif",
    "strength_disagree": "accords où les deux modèles divergent sur la force de la clause",
    "pay_unspecified": "accords qui ne disent rien de l'effet sur la rémunération",
    "pay_unspecified_share": "part des accords lus qui ne disent rien de l'effet sur la rémunération",
    "pay_unpaid_recovery": "accords où les heures perdues sont à récupérer, sans rémunération",
    "pay_extra": "accords prévoyant un supplément ou une prime",
    "pay_maintained": "accords prévoyant le maintien de la rémunération",
    "pay_none": "accords disant explicitement qu'il n'y a aucune compensation",
    "scope_unspecified": "accords qui ne disent pas à qui la clause s'applique",
    "scope_vulnerable": "accords visant les salariés vulnérables",
    "proc_cse": "accords prévoyant la consultation ou l'information du CSE",
    "proc_consent": "accords prévoyant le volontariat ou le consentement du salarié",
    "collected": "accords collectés (tous)",
    "years": "période de signature des accords collectés",
    "heat_loose": "accords contenant une clause chaleur (au moins un des deux modèles)",
    "heat_strict": "accords contenant une clause chaleur (les deux modèles)",
    "specific": "accords ayant une clause propre à la chaleur (dispositif dédié)",
    "specific_share": "part de ces accords parmi ceux où les deux modèles lisent une clause chaleur",
    "generic": "accords où la chaleur n'est qu'un cas d'une clause générale (intempéries, circonstances exceptionnelles...)",
    "generic_share": "part de ces accords parmi ceux où les deux modèles lisent une clause chaleur",
    "decree": "accords citant le décret n° 2025-482 (recherche de mots-clés, pas un codage)",
    "withdrawal": "accords citant le droit de retrait, déjà accompagné du nom (« 2 accords »), recherche de mots-clés dans les extraits",
    "telework": "accords dont la clause relève du télétravail",
    "telework_exceptional": "parmi eux, accords où le télétravail répond à des circonstances exceptionnelles (épidémie, pollution, grève, intempéries), recherche de mots-clés",
    "telework_exceptional_share": "part de ces accords parmi les accords de télétravail",
    "template_agreements": "accords qui reprennent une clause partagée avec au moins une autre entreprise",
    "template_share": "part de ces accords parmi ceux qui parlent de chaleur",
    "template_groups": "nombre de groupes d'accords partageant une même clause",
    "template_largest": "nombre d'accords du plus grand de ces groupes",
    "temperature_agreements": "accords citant une température (lecture large)",
    "threshold_30": "accords citant 30 °C (lecture large)",
    "threshold_28": "accords citant 28 °C (lecture large)",
    "telework_peak_year": "année où la part du télétravail est la plus élevée (années d'au moins 100 accords collectés, hors année partielle)",
    "telework_peak": "part du télétravail cette année-là, parmi les accords collectés cette année-là",
    "telework_last": "part du télétravail la dernière année complète",
    "prevention_last": "part de la prévention la dernière année complète",
    "last_year": "dernière année complète",
    "partial_year": "dernière année, partielle",
    "prevention_partial": "part de la prévention l'année partielle",
}


class ChatText(Protocol):
    def chat_text(self, system: str, user: str, *, max_tokens: int) -> str: ...


class PolishError(RuntimeError):
    pass


_PLACEHOLDER = re.compile(r"#f\.([a-z_0-9]+)")
_QUOTE = re.compile(r'#q\("([a-z_0-9]+)"\)')
_HEADING = re.compile(r"^(=+) ", re.MULTILINE)
_DIGITS = re.compile(r"\d+")
_FORBIDDEN = ("$", "@", "`")
# words that make a claim stronger or absolute: allowed only where the draft has them
_ABSOLUTES = re.compile(
    r"\b(requis|requise|exige\w*|impos\w+|systématique\w*|toujours|jamais|tous|toutes"
    r"|aucun\w*|seul\w*|uniquement|exclusi\w+|quasi\w*|majorit\w+|minorit\w+"
    r"|la plupart|unanim\w+|partout|nécessairement|obligatoirement)\b",
    re.IGNORECASE,
)


def split_template(source: str, start: str = START) -> tuple[str, str]:
    """The preamble (kept as is) and the prose, which starts at the `start` line."""
    at = source.index(start)
    return source[:at], source[at:]


def placeholders(prose: str) -> set[str]:
    return set(_PLACEHOLDER.findall(prose))


def _digits(prose: str) -> set[str]:
    bare = _QUOTE.sub("", _PLACEHOLDER.sub("", prose))
    return set(_DIGITS.findall(bare))


def _words(prose: str) -> int:
    return len(prose.split())


def _absolutes(prose: str) -> dict[str, str]:
    """The strong words of a text by stem, so that "seul" and "seules" are one."""
    return {
        re.sub(r"(es|e|s)$", "", w.lower()): w.lower()
        for w in _ABSOLUTES.findall(prose)
    }


def check(original: str, revised: str) -> list[str]:
    """What is wrong with a revised prose, compared with the draft; [] if it is fine."""
    errors = []
    names, kept = placeholders(original), placeholders(revised)
    if missing := sorted(names - kept):
        errors.append(f"placeholders missing: {', '.join('#f.' + n for n in missing)}")
    if added := sorted(kept - names):
        errors.append(f"placeholders added: {', '.join('#f.' + n for n in added)}")
    quotes, revised_quotes = _QUOTE.findall(original), _QUOTE.findall(revised)
    if sorted(quotes) != sorted(revised_quotes):
        errors.append(
            f"#q calls differ: expected each of {sorted(quotes)} exactly once, "
            f"got {sorted(revised_quotes)}"
        )
    if (a := original.count("#lead[")) > (b := revised.count("#lead[")):
        errors.append(f"#lead[ wrappers: at least {a} expected, got {b}")
    levels, revised_levels = _HEADING.findall(original), _HEADING.findall(revised)
    if [len(x) for x in levels] != [len(x) for x in revised_levels]:
        errors.append(
            f"headings differ: expected levels {[len(x) for x in levels]}, "
            f"got {[len(x) for x in revised_levels]}"
        )
    if new := sorted(_digits(revised) - _digits(original)):
        errors.append(f"digits not in the draft: {', '.join(new)}")
    for char in _FORBIDDEN:
        if char in revised and char not in original:
            errors.append(f"forbidden character {char!r}")
    drafted = _absolutes(original)
    if stronger := sorted(
        w for stem, w in _absolutes(revised).items() if stem not in drafted
    ):
        errors.append(
            f"stronger or absolute words not in the draft: {', '.join(stronger)}"
        )
    if revised.count("[") != revised.count("]"):
        errors.append("unbalanced square brackets")
    first, last = original.strip().splitlines(), revised.strip().splitlines()
    if not last or last[0] != first[0]:
        errors.append(f"first line must stay exactly: {first[0]}")
    if not last or last[-1] != first[-1]:
        errors.append(f"last line must stay exactly: {first[-1]}")
    if _words(revised) > MAX_GROWTH * _words(original):
        errors.append(
            f"too long: {_words(revised)} words, at most "
            f"{int(MAX_GROWTH * _words(original))}"
        )
    return errors


def build_user(
    prose: str,
    f: Mapping[str, str],
    quotes: Mapping[str, Mapping[str, str]],
    meanings: Mapping[str, str] = MEANINGS,
) -> str:
    """The message: glossary with the live values, quotes (read-only), the draft."""
    unknown = sorted(placeholders(prose) - set(meanings))
    if unknown:
        raise PolishError(f"no meaning for: {', '.join(unknown)}")
    glossary = "\n".join(
        f"- #f.{name} = {f[name]} : {meanings[name]}"
        for name in sorted(placeholders(prose))
    )
    cited = "\n".join(
        f'- #q("{key}") : « {q["text"]} » ({q["company"]}, {q["year"]})'
        for key, q in quotes.items()
        if key in set(_QUOTE.findall(prose))
    )
    return (
        "# Glossaire des marqueurs #f.<nom> (valeur actuelle : sens)\n"
        f"{glossary}\n\n"
        '# Citations affichées par #q("clé") (lecture seule)\n'
        f"{cited}\n\n"
        "# Brouillon à réécrire (Typst)\n"
        f"{prose}\n"
    )


def _between(text: str, start: str, end: str) -> str | None:
    found = re.search(re.escape(start) + r"(.*?)" + re.escape(end), text, re.DOTALL)
    return found.group(1).strip() if found else None


def parse_answer(answer: str) -> tuple[str, str]:
    """(Typst prose, notes) from the model's answer; raises if the Typst block is absent."""
    typst = _between(answer, "<<<TYPST", "TYPST>>>")
    if typst is None:
        raise PolishError("no <<<TYPST ... TYPST>>> block in the answer")
    typst = re.sub(r"^```[a-z]*\n|\n```$", "", typst).strip()
    return typst + "\n", _between(answer, "<<<NOTES", "NOTES>>>") or ""


def _retry(user: str, previous: str, errors: list[str]) -> str:
    """The request again, with the rejected answer and what to fix in it."""
    fixes = "\n".join(f"- {e}" for e in errors)
    if not previous:
        return f"{user}\n\n# Ta réponse précédente a été rejetée\n{fixes}\n\nRéponds à nouveau."
    return (
        f"{user}\n\n# Ta réponse précédente (rejetée)\n<<<TYPST\n{previous}TYPST>>>\n\n"
        f"# À corriger\n{fixes}\n\nReprends ta réponse précédente et corrige uniquement "
        "ces points, en changeant le moins de mots possible. Même format de réponse "
        "(<<<TYPST ... TYPST>>> puis <<<NOTES ... NOTES>>>)."
    )


def polish(
    chat: ChatText,
    template_source: str,
    f: Mapping[str, str],
    quotes: Mapping[str, Mapping[str, str]],
    *,
    system: str = SYSTEM,
    meanings: Mapping[str, str] = MEANINGS,
    start: str = START,
) -> tuple[str, str]:
    """(new template source, notes). Each answer is checked against the draft; a rejected
    one is sent back with its errors. Raises PolishError if no attempt passes. The
    defaults polish the report; a note passes its own prompt, glossary and first line."""
    preamble, prose = split_template(template_source, start)
    user = build_user(prose, f, quotes, meanings)
    request, errors = user, []
    for _ in range(MAX_ATTEMPTS):
        previous = ""
        try:
            revised, notes = parse_answer(
                chat.chat_text(system, request, max_tokens=MAX_TOKENS)
            )
        except PolishError as error:
            errors = [str(error)]
        else:
            errors = check(prose, revised)
            if not errors:
                return preamble + revised, notes
            previous = revised
        request = _retry(user, previous, errors)
    raise PolishError("every attempt was rejected: " + "; ".join(errors))
