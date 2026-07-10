import re
from typing import Optional, TypedDict

from nltk.tokenize import TreebankWordTokenizer

_tokenizer = TreebankWordTokenizer()

# FIXME: borrowed from fiche MT data package in JS, converted to Python by AI

NEGATIVE = "O"
ARTICLE = "B-ART"
CODE_PREFIX = "B-COD"
CODE_TRA = CODE_PREFIX + "_TRA"
CODE_SS = CODE_PREFIX + "_SS"
CODE_OTHER = CODE_PREFIX + "_O"

UNRECOGNIZED = "unrecognized"

CODE_TRAVAIL = {
    "id": "LEGITEXT000006072050",
    "name": "code du travail",
}

CODE_SECU = {
    "id": "LEGITEXT000006073189",
    "name": "code de la sécurité sociale",
}

codes_full_names = {
    CODE_SS: CODE_SECU,
    CODE_TRA: CODE_TRAVAIL,
}

range_ = 20  # max distance between code tokens and corresponding article ref

article_regex = re.compile(r"^(\d{1,4}(-\d+){0,3})\b")


def article_matcher(token: str):
    return article_regex.match(token)


valid_prefix = ["l", "r", "d"]


def prefix_matcher(token: str) -> int:
    low_token = token.lower()
    matching_prefix = any(low_token.startswith(p) for p in valid_prefix)

    if matching_prefix:
        residual = low_token[1:]

        if not residual:
            return 1
        elif residual == ".":
            return 1
        elif residual[:1] == "." and article_matcher(residual[1:]):
            return 2
        elif article_matcher(residual[1:]):
            return 2

    return 0


def infix_matcher(token: str) -> bool:
    return token in ["à", "\u00e0"]


def classify_tokens(tokens: list[str]) -> list[str]:
    # step 1: check for prefix matches or articles
    step1 = []
    for token in tokens:
        prefix = prefix_matcher(token)
        infix = infix_matcher(token)
        article = article_matcher(token)

        if prefix > 0:
            step1.append(prefix)
        elif article:
            step1.append(3)
        elif infix:
            step1.append(4)
        else:
            step1.append(0)

    # step 2: confirm valid sequences
    predictions = [[]]  # last element is the buffer

    for e in step1:
        buffer = predictions[-1]
        in_sequence = len(buffer) > 0
        last_element = buffer[-1] if buffer else None

        if e >= 1 and in_sequence:
            buffer.append(e)
        elif e == 0 and in_sequence and last_element and last_element > 1:
            predictions.pop()
            for _ in buffer:
                predictions.append(True)  # type: ignore
            predictions.append(False)  # type: ignore
            predictions.append([])
        elif e > 0 and e < 3 and not in_sequence:
            buffer.append(e)
        else:
            predictions.pop()
            for _ in buffer:
                predictions.append(False)  # type: ignore
            predictions.append(False)  # type: ignore
            predictions.append([])

    # conclude
    residual = predictions.pop()
    if len(residual) > 0 and residual[-1] > 1:
        for _ in residual:
            predictions.append(True)  # type: ignore
    else:
        for _ in residual:
            predictions.append(False)  # type: ignore

    return [ARTICLE if p else NEGATIVE for p in predictions]


def identify_codes(tokens: list[str], predictions: list[str]) -> list[str]:
    match_code = [
        CODE_PREFIX if token.lower() == "code" else predictions[i]
        for i, token in enumerate(tokens)
    ]

    resolved = []
    for i, pred in enumerate(match_code):
        if pred == CODE_PREFIX:
            joined = " ".join(tokens[i : i + 5]).lower()
            if joined.startswith(codes_full_names[CODE_SS]["name"]):
                resolved.append(CODE_SS)
            elif joined.startswith(codes_full_names[CODE_TRA]["name"]):
                resolved.append(CODE_TRA)
            else:
                resolved.append(CODE_OTHER)
        else:
            resolved.append(pred)

    return resolved


class Reference(TypedDict):
    code: Optional[dict]
    text: str


def extract_references(text: str) -> list[Reference]:
    tokens = treebank_tokenize(text)
    predictions = classify_tokens(tokens)
    predictions = identify_codes(tokens, predictions)

    acc = []
    for index, (token, pred) in enumerate(zip(tokens, predictions)):
        if pred == ARTICLE:
            if not acc:
                acc.append({"index": index, "token": token})
            else:
                last = acc[-1]
                if last["index"] + 1 == index:
                    last["token"] = f"{last['token']} {token}"
                    last["index"] = index
                else:
                    acc.append({"index": index, "token": token})
        elif pred.startswith(CODE_PREFIX) and acc:
            for match in acc:
                if not match.get("code") and match["index"] + range_ >= index:
                    if pred in codes_full_names:
                        match["code"] = codes_full_names[pred]
                    else:
                        match["code"] = UNRECOGNIZED

    return [
        {"code": m.get("code"), "text": m["token"]}
        for m in acc
        if not m.get("code") or m.get("code") != UNRECOGNIZED
    ]


def treebank_tokenize(text: str) -> list[str]:
    return _tokenizer.tokenize(text)
