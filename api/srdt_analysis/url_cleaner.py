import regex

from srdt_analysis.constants import CHUNK_INDEX
from srdt_analysis.elastic_handler import ElasticIndicesHandler

whitelist = [
    "legifrance.gouv.fr",
    "travail-emploi.gouv.fr",
    "defenseurdesdroits.fr",
    "francetravail.fr",
    "antidiscriminations.fr",
    "defenseurdesdroits.fr",
    "service-public.fr",
    "dreets.gouv.fr",
    "cnil.fr",
    "ags-garantie-salaires.org",
    "ameli.fr",
    "info-retraite.fr",
    "travail-emploi.gouv.fr",
    "travail-emploi.gouv.fr/inspection-du-travail",
    "msa.fr",
    "transitionspro.fr",
    "travail-emploi.gouv.fr",
    "moncompteformation.gouv.fr",
    "mon-cep.org",
    "agefiph.fr",
    "service-public.fr",
    "info-retraite.fr",
    "avft.org",
    "net-entreprises.fr",
    "francetravail.fr",
]

es = ElasticIndicesHandler()


def to_comparable_path(url: str):
    replaced = url.replace("https://", "").replace("www.", "")
    if replaced.endswith("/"):
        replaced = replaced[0 : len(replaced) - 1]

    return replaced


def clean_urls(response: str):
    """Remove broken urls contained in llm response, it
    might be hallucinations, wrong domains or bad format.
    """
    pattern = regex.compile(r"\[([^][]+)\](\(((?:[^()]+|(?2))+)\))")

    cdtn = []
    cdtn_error = []
    legifrance = []
    unknown = []
    out_ok = []

    def remove_from_response(resp: str, url: str, description: str):
        # case where link looks like ([Source](https://.....))
        if (
            description.lower()
            in [
                "source",
                "lien",
                "ici",
            ]
            or description.startswith("www")
            or description.startswith("http")
        ):
            return resp.replace(f"[{description}]({url})", "").replace("()", "")
        # case where we want to keep the description in the text
        else:
            return resp.replace(f"[{description}]({url})", description)

    for match in pattern.finditer(response):
        description, _, url = match.groups()

        # print(f"{description}: {url}")
        path = to_comparable_path(url)
        if path.startswith("code.travail.gouv.fr"):
            check = es.check_urls(CHUNK_INDEX, [url])
            if url != "https://code.travail.gouv.fr/" and not check[0][1]:
                cdtn_error.append(url)
                response = remove_from_response(response, url, description)
            else:
                cdtn.append(url)

        elif path in whitelist:
            out_ok.append(url)

        # we remove link if legifrance or unknown
        else:
            if "legifrance.gouv.fr" in url:
                legifrance.append(url)
            else:
                unknown.append(url)

            response = remove_from_response(response, url, description)

    return response
