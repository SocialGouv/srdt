import regex

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
    legifrance = []
    unknown = []
    out_ok = []

    for match in pattern.finditer(response):
        description, _, url = match.groups()

        # print(f"{description}: {url}")
        path = to_comparable_path(url)
        if path.startswith("code.travail.gouv.fr"):
            cdtn.append(url)

        elif path in whitelist:
            out_ok.append(url)

        # we remove link if legifrance or unknown
        else:
            if "legifrance.gouv.fr" in url:
                legifrance.append(url)
            else:
                unknown.append(url)

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
                response = response.replace(f"[{description}]({url})", "").replace(
                    "()", ""
                )
            # case where we want to keep the description in the text
            else:
                response = response.replace(f"[{description}]({url})", description)

    return response
