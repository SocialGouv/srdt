import regex


# remove broken urls contained in llm response
# hallucinations or wrong domains
def clean_urls(response: str):
    pattern = regex.compile(r"\[([^][]+)\](\(((?:[^()]+|(?2))+)\))")

    cdtn = []
    legifrance = []
    unknown = []
    for match in pattern.finditer(response):
        description, _, url = match.groups()
        # print(f"{description}: {url}")
        if url.startswith("https://code.travail.gouv.fr"):
            cdtn.append(url)
        elif "legifrance.gouv.fr" in url:
            legifrance.append(url)
        else:
            unknown.append(url)
            # case where link looks like ([Source](https://.....))
            if description.lower() in ["source", "lien", "ici"]:
                # print(f"delete [{description}]({url})")
                response = response.replace(f"[{description}]({url})", "").replace(
                    "()", ""
                )
            # case where we want to keep the description in the text
            else:
                # print(f"replace [{description}]({url}) -> {description}")
                response = response.replace(f"[{description}]({url})", description)

    # print([cdtn, legifrance, unknown])
    # print(response)

    return response
