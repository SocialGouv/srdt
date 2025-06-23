# type: ignore

from transformers import AutoTokenizer, AutoModelForTokenClassification
from transformers.pipelines import pipeline

ano_tokenizer = AutoTokenizer.from_pretrained("Jean-Baptiste/camembert-ner")
model = AutoModelForTokenClassification.from_pretrained("Jean-Baptiste/camembert-ner")
nlp = pipeline(
    "ner", model=model, tokenizer=ano_tokenizer, aggregation_strategy="simple"
)

entities_fr = {"ORG": "ENTREPRISE", "PER": "PERSON", "LOC": "LIEU"}
keys = entities_fr.keys()


def run_ano(user_question):
    entities = nlp(user_question)

    for e in entities:
        group = e["entity_group"]
        if group in keys:
            user_question = user_question.replace(e["word"], entities_fr[group])

    return user_question
