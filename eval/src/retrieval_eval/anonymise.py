"""Question anonymisation for the eval queries.

Starts from the production step (`api/srdt_analysis/text/anonymiser.py`: spaCy
`fr_core_news_md`, ORG -> ENTREPRISE, PER -> PERSONNE) and fixes what it gets wrong
on real questions, measured on the Feb 2026 export:

- false positives: the NER takes legal vocabulary for entities ("CDD", "CPH",
  "LICENCIEMENT", "Convention collective nationale" -> ENTREPRISE, a bare "Monsieur"
  -> PERSONNE) and mangles the query that is then searched;
- misses: first names, ALL-CAPS surnames and companies, towns, "employeur X".

So the spaCy entities are filtered (`_ner_spans`) and completed by rules (titles,
company cues, rare ALL-CAPS or capitalised words). `anonymise_regex` adds the
identifiers spaCy does not catch (SIRET/SIREN, phone numbers, emails).

"Rare" is read from the word vectors of the spaCy model, which are ordered by
frequency: a word is common when its lower-cased form is in the first
`RARE_RANK` rows. Names, towns and brands fall outside, French words inside.
This is a heuristic: it keeps a few common-word names (a surname such as "Martin"
mid-sentence is still caught by the NER, "KFC" is not), so the output must still be
read by hand before it is shared.
"""

import re
import unicodedata
from functools import lru_cache

ENTITIES_FR = {"ORG": "ENTREPRISE", "PER": "PERSONNE", "LOC": "LIEU"}

# Words of the model vocabulary beyond this frequency rank are "rare".
RARE_RANK = 12_000
# A lone capitalised word below this rank is an ordinary noun ("Titre"), not a name.
VERY_COMMON_RANK = 3_000
# Above this share of upper-case letters a text is shouted: the NER is noise there.
SHOUTING_RATIO = 0.6

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# SIRET (14 digits) / SIREN (9 digits), optionally space separated
_SIRET = re.compile(r"(?<!\d)(?:\d[ .]?){13}\d(?!\d)")
_SIREN = re.compile(r"(?<!\d)\d{3}[ .]?\d{3}[ .]?\d{3}(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:(?:\+|00)33[ .]?|0)[1-9](?:[ .-]?\d{2}){4}(?!\d)")

_WORD = re.compile(r"[^\W\d_][\w'’-]*")
_UPPER_INITIAL = r"[A-ZÀ-ÖØ-Þ]"
_NAME_WORD = rf"{_UPPER_INITIAL}[\w'’-]*"
_TITLE_NAME = re.compile(
    rf"\b(?i:Monsieur|Madame|Mademoiselle|Mme|Mlle|Mr|M\.)[ \t]+"
    rf"({_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,2}})"
)
# employer cue followed by a name: "employeur EURONOR", "chez LIDL", "société Foo"
_COMPANY_CUE = re.compile(
    r"\b(?i:employeur|employeuse|société|societe|entreprise|chez|enseigne|magasin"
    rf"|association|groupe|boîte|boite)[ \t]+({_NAME_WORD})"
)
_ALL_CAPS_WORD = re.compile(r"\b[A-ZÀ-ÖØ-Þ]{4,}\b")
_CAPITALISED_WORD = re.compile(rf"\b{_UPPER_INITIAL}[a-zà-öø-ÿ'’-]{{3,}}\b")

# Everything below is compared after `_norm` (lower case, no accents).
# Salutations and glue words that the NER glues to names.
_NOT_NAME = {
    "monsieur", "madame", "mademoiselle", "mme", "mlle", "mr", "m", "ce", "cette",
    "sachez", "sachant", "cordialement", "bonjour", "bonsoir", "merci", "le", "la",
    "les", "l", "un", "une", "du", "de", "des", "d", "et", "ou", "je", "il", "elle",
    "on", "nous", "vous", "ils", "mon", "ma", "mes", "son", "sa", "ses", "notre",
    "directeur", "directrice", "responsable", "president", "presidente",
    "gerant", "gerante", "patron", "patronne", "employeur", "salarie", "salariee",
    "docteur", "dr", "maitre", "me",
}  # fmt: skip

# Domain vocabulary that must survive: acronyms, institutions, legal nouns the NER or
# the rare-word rule would otherwise take for a name.
_KEEP = {
    # work-law acronyms
    "cse", "cssct", "rpx", "ij", "cp", "cdd", "cdi", "cdic", "rtt", "cet", "cfa",
    "cpam", "caf", "msa", "cph", "cnil", "cpf", "opco", "pse", "rcc", "dpae", "due",
    "dsn", "smic", "ccn", "ccnt", "cppni", "idcc", "iddc", "etam", "esat", "ehpad",
    "haccp", "mecs", "cuma", "hcr", "btp", "ash", "at", "mp", "are", "rsa", "apl",
    "pai", "sst", "mist", "cap", "bep", "bts", "dut", "vae", "tese", "ddets",
    "dreets", "direccte", "urssaf", "fehap", "sas", "sasu", "sarl", "eurl", "scop",
    "cesu", "pacs", "cerfa", "unedic", "agirc", "arrco", "pajemploi", "legifrance",
    "pdf", "csp", "smpt", "pee", "perco", "per", "qvt", "ape", "naf", "ett",
    # institutions and places that are vocabulary, not identity
    "france", "france travail", "pole emploi", "securite sociale", "secu",
    "inspection du travail", "conseil de prud'hommes", "cour de cassation",
    "ministere du travail", "alsace", "moselle", "alsace-moselle", "guadeloupe",
    "martinique", "guyane", "reunion", "mayotte", "outre-mer", "europe", "etat",
    "union europeenne", "dom", "tom",
    # work-law acronyms met in the export
    "rqth", "mdph", "ijss", "ccntrv", "siap", "ssiap", "aemo", "siae", "carsat",
    "afgsu", "ibode", "duerp", "rgpd", "ddtm", "dreal", "cddi", "cdii", "cdie",
    "cibtp", "akto", "unifed", "ephad", "hepad", "ifse", "rg", "pro-a", "scm",
    "sad", "idr", "ct", "cesa", "brut", "net", "syntec", "mac-sst", "report",
    "boulangerie", "patisserie", "anonyme", "carence", "inapte", "usager", "quote",
    "unquote", "quid", "indetermine", "salariee", "facon", "pere", "viii", "jai",
    # the placeholders themselves
    "personne", "entreprise", "lieu", "email", "telephone", "siret", "siren",
    # dates
    "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
    "septembre", "octobre", "novembre", "decembre", "lundi", "mardi", "mercredi",
    "jeudi", "vendredi", "samedi", "dimanche",
}  # fmt: skip
# Capitalised nouns the NER tags as places.
_KEEP_LOC = {
    "anciennete", "regle", "resultat", "majoration", "alliance", "art", "article",
    "coefficient", "echelon", "groupe", "niveau", "classe", "categorie", "cadre",
    "agent", "maitrise", "plage", "cour", "services", "domicile", "defense",
    "francais", "vendeuse", "mines", "eglise", "vestiaires", "handicape", "titre",
}  # fmt: skip


@lru_cache(maxsize=1)
def _nlp():
    import spacy

    return spacy.load(
        "fr_core_news_md",
        disable=["tok2vec", "tagger", "parser", "attribute_ruler", "lemmatizer"],
    )


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower().replace("’", "'"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.split())


def _rank(word: str) -> int | None:
    vocab = _nlp().vocab
    return vocab.vectors.key2row.get(vocab[word.lower()].orth)


def _is_rare(word: str) -> bool:
    """Not among the most frequent French words of the model (names, brands, typos).

    "Est-ce" or "J'ai" are rare as a whole but made of everyday words: check the parts.
    """
    parts = [p for p in re.split(r"['’-]", word) if len(p) > 2]
    return any((r := _rank(p)) is None or r >= RARE_RANK for p in parts)


def _is_very_common(word: str) -> bool:
    return all(
        (r := _rank(p)) is not None and r < VERY_COMMON_RANK
        for p in re.split(r"['’-]", word)
        if len(p) > 2
    )


def _kept(text: str) -> bool:
    return _norm(text) in _KEEP


def _shouting(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 12 and sum(c.isupper() for c in letters) / len(letters) > (
        SHOUTING_RATIO
    )


def _sentence_initial(text: str, start: int) -> bool:
    before = text[:start].rstrip(" \t\"'«-*•(")
    return not before or before[-1] in ".!?:;\n"


Span = tuple[int, int, str]


def _words(text: str, offset: int = 0) -> list[tuple[int, int, str]]:
    return [
        (offset + m.start(), offset + m.end(), m.group()) for m in _WORD.finditer(text)
    ]


def _title_spans(text: str) -> list[Span]:
    spans = []
    for m in _TITLE_NAME.finditer(text):
        name = m.group(1)
        words = _words(name, m.start(1))
        # keep the leading words that can be a name ("Monsieur Le Directeur" is none)
        good = []
        for w in words:
            if _norm(w[2]) in _NOT_NAME:
                break
            good.append(w)
        if good:
            spans.append((m.start(), good[-1][1], ENTITIES_FR["PER"]))
    return spans


def _cue_spans(text: str) -> list[Span]:
    spans = []
    for m in _COMPANY_CUE.finditer(text):
        word = m.group(1)
        if _norm(word) in _KEEP or _norm(word) in _NOT_NAME or not _is_rare(word):
            continue
        spans.append((m.start(1), m.end(1), ENTITIES_FR["ORG"]))
    return spans


def _free_word_spans(text: str) -> list[Span]:
    """Words the model has never seen, or shouted rare ones: surnames, brands, towns.

    Capitalised words are only taken when unknown to the vocabulary (a rare but real
    noun such as "Handicapé" must stay). Runs of three or more shouted words are
    emphasis ("JE N AI PAS DE DIPLOME"), not names.
    """
    spans = []
    caps_run: list[tuple[int, int, str]] = []

    def flush() -> None:
        if len(caps_run) < 3:
            for start, end, word in caps_run:
                if _norm(word) not in _KEEP and _is_rare(word):
                    spans.append((start, end, ENTITIES_FR["ORG"]))
        caps_run.clear()

    previous_end = 0
    for start, end, word in _words(text):
        if any(c.isdigit() for c in word):
            flush()
            continue
        letters = [c for c in word if c.isalpha()]
        if len(letters) >= 4 and all(c.isupper() for c in letters) and "'" not in word:
            if caps_run and text[previous_end:start].strip():
                flush()
            caps_run.append((start, end, word))
            previous_end = end
            continue
        flush()
        if (
            word[0].isupper()
            and not _sentence_initial(text, start)
            and len(word) > 3
            and _norm(word) not in _KEEP | _KEEP_LOC | _NOT_NAME
            and not any(c.isupper() for c in word[1:] if c.isalpha())
            and any(_rank(p) is None for p in re.split(r"['’-]", word) if len(p) > 2)
        ):
            spans.append((start, end, ENTITIES_FR["ORG"]))
    flush()
    return spans


def _trim_lowercase_edges(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Narrow a span to its capitalised core ("port du Havre" -> "Havre")."""
    words = [w for w in _words(text[start:end], start) if w[2][0].isupper()]
    return (words[0][0], words[-1][1]) if words else None


_PLACE_CUE = re.compile(
    r"(?:\b(?:à|au|aux|en|dans|sur|vers|près|de|du|des|d|ville|commune|département)"
    r"[ \t']+(?:(?:la|le|les|l)[ \t']+)?)$",
    re.I,
)


def _after_place_cue(text: str, start: int) -> bool:
    return bool(_PLACE_CUE.search(text[max(0, start - 20) : start].replace("’", "'")))


def _ner_span(text: str, ent) -> Span | None:
    label = ent.label_
    if label not in ENTITIES_FR:
        return None
    span = _trim_lowercase_edges(text, ent.start_char, ent.end_char)
    if span is None:
        return None
    start, end = span
    surface = text[start:end]
    if any(c.isdigit() for c in surface) or _kept(surface):
        return None
    # what is left once salutations, glue words and domain vocabulary are set aside
    words = [
        w
        for w in _words(surface, start)
        if _norm(w[2]) not in _NOT_NAME and _norm(w[2]) not in _KEEP
    ]
    if not words or _norm(surface).startswith(("convention collective", "ccn")):
        return None
    start, end = words[0][0], words[-1][1]
    surface = text[start:end]

    if label == "ORG":
        # a legal term, a public body, a convention title: all words are everyday ones
        if not any(_is_rare(w[2]) for w in words):
            return None
    elif label == "PER":
        if len(words) == 1:
            # "Titre", "Informations", "Sachant": an everyday word, not a person
            if _is_very_common(words[0][2]):
                return None
            if _sentence_initial(text, start) and not _is_rare(words[0][2]):
                return None
        elif "\n" in surface or any(w[2][0].islower() for w in _words(surface)):
            # "Titre de Séjour": not a name as a whole
            return None
    else:  # LOC
        if surface.isupper() or len(surface) < 4:
            return None
        if all(_norm(w[2]) in _KEEP_LOC for w in words):
            return None
        if not any(_is_rare(w[2]) for w in words) and not _after_place_cue(text, start):
            return None  # common words with no "à", "du", "en" before: not a place
    return start, end, ENTITIES_FR[label]


def _ner_spans(text: str) -> list[Span]:
    spans = (_ner_span(text, ent) for ent in _nlp()(text).ents)
    return [s for s in spans if s is not None]


def _merge(spans: list[Span]) -> list[Span]:
    """Overlapping spans become one. PERSONNE wins over ENTREPRISE over LIEU."""
    priority = {"PERSONNE": 0, "ENTREPRISE": 1, "LIEU": 2}
    merged: list[Span] = []
    for start, end, token in sorted(spans):
        if merged and start < merged[-1][1]:
            prev_start, prev_end, prev_token = merged[-1]
            best = min(prev_token, token, key=priority.__getitem__)
            merged[-1] = (prev_start, max(prev_end, end), best)
        else:
            merged.append((start, end, token))
    return merged


def anonymise_regex(question: str) -> str:
    out = _EMAIL.sub("EMAIL", question)
    # order matters: the phone pattern must run before SIREN, whose 9 digits it contains
    out = _PHONE.sub("TELEPHONE", out)
    out = _SIRET.sub("SIRET", out)
    return _SIREN.sub("SIREN", out)


def anonymise_names(text: str) -> str:
    """Replace people, companies and places (everything the regexes cannot see)."""
    spans = _title_spans(text)
    if not _shouting(text):
        spans += _cue_spans(text) + _ner_spans(text) + _free_word_spans(text)
    out = text
    for start, end, token in reversed(_merge(spans)):
        out = out[:start] + token + out[end:]
    return out


def anonymise(question: str) -> str:
    return anonymise_names(anonymise_regex(question))
