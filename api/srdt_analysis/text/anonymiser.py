import spacy

from srdt_analysis.core.exceptions import SRDTException
from srdt_analysis.core.logger import Logger

nlp = spacy.load(
    "fr_core_news_md",
    disable=["tok2vec", "tagger", "parser", "attribute_ruler", "lemmatizer"],
)

entities_fr = {"ORG": "ENTREPRISE", "PER": "PERSONNE"}


# we don't want to replace those tokens
restricted_token = ["CSE", "CSSCT", "RPX", "IJ", "CP"]

logger = Logger("Anonymizer")


def anonymise_spacy(question: str):
    try:
        doc = nlp(question)

        anonymised = question

        # replace entities
        for ent in reversed(doc.ents):
            start = ent.start_char
            end = start + len(ent.text)
            label_en = ent.label_
            if label_en in entities_fr.keys() and ent.text not in restricted_token:
                anonymised = (
                    anonymised[:start] + entities_fr[label_en] + anonymised[end:]
                )
        return anonymised
    except ValueError as ve:
        message = f"Anonymize validation error: {str(ve)}"
        logger.error(message)
        raise SRDTException(message=message)
