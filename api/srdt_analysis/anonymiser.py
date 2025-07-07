import spacy

nlp = spacy.load(
    "fr_core_news_md",
    disable=["tok2vec", "tagger", "parser", "attribute_ruler", "lemmatizer"],
)

entities_fr = {"ORG": "ENTREPRISE", "PER": "PERSONNE", "LOC": "LIEU"}


def anonymise_spacy(question: str):
    doc = nlp(question)

    anonymised = question

    # replace entities
    for ent in reversed(doc.ents):
        start = ent.start_char
        end = start + len(ent.text)
        label_en = ent.label_
        if label_en in entities_fr.keys():
            anonymised = anonymised[:start] + entities_fr[label_en] + anonymised[end:]

    return anonymised
