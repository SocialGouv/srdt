"""out/flavours.md and out/flavours.csv from the result of flavours.build."""

from typing import Any

DIMENSION_TITLES = {
    "measures": "Mesures",
    "triggers": "Déclencheurs",
    "pay": "Rémunération",
    "scope": "Public",
    "initiative": "Initiative",
    "procedure": "Procédure",
    "strength": "Portée",
}


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.0f} %"


def _ci(ci: list[float] | None) -> str:
    return "" if not ci else f" ({ci[0] * 100:.0f}–{ci[1] * 100:.0f})"


def _distribution_lines(distributions: dict[str, list[dict[str, Any]]]) -> list[str]:
    return [
        f"- **{DIMENSION_TITLES[d]}** : "
        + ", ".join(f"{r['label']} {_pct(r['share'])}" for r in rows)
        for d, rows in distributions.items()
    ]


def to_markdown(result: dict[str, Any]) -> str:
    out = [
        "# Nuances des clauses chaleur, par famille",
        "",
        f"Snapshot `{result.get('snapshot', '')}`. Généré par `acco-analysis flavours`.",
        "",
        "## Comment lire",
        "",
        "- Une **nuance** est une combinaison de caractéristiques (mesure, déclencheur, "
        "effet sur la rémunération ; pour le télétravail aussi initiative, procédure et "
        "public) qui revient dans plusieurs accords d'une famille. Les combinaisons et "
        "leurs effectifs sont **comptés dans les codages**, pas écrits par le modèle.",
        "- Les accords retenus sont ceux que **les deux modèles** ont codés (lecture "
        "stricte). Les nuances sont cherchées de la plus spécifique à la plus générale : "
        "un accord n'est dans **qu'une seule** nuance, la première qui lui correspond. "
        "Une nuance courte (par exemple « horaires décalés ») regroupe donc les accords "
        "qui n'ont pas de combinaison plus précise.",
        "- La colonne « large » compte les accords dont le codage large (l'un ou "
        "l'autre modèle) contient ces caractéristiques, sans retirer ceux déjà placés "
        "ailleurs : c'est un majorant qui chevauche les autres lignes.",
        "- Le **nom** et la **description** sont écrits par le modèle à partir de six à "
        "huit extraits représentatifs et des répartitions comptées ; ils ne sont pas "
        "vérifiés à la main. Les **citations** sont vérifiées mot pour mot dans le texte "
        "de l'accord ; celles qui ne l'étaient pas sont écartées.",
        "- Un modèle de clause partagé par plusieurs entreprises compte pour chacune ; "
        "« gabarits » compte une clause commune une seule fois.",
        "",
    ]
    for family in result["families"].values():
        covered = family["strict"] - family["other"]["strict"]
        out += [
            f"## {family['label']}",
            "",
            f"{family['strict']} accords (lecture stricte), {family['loose']} en lecture "
            f"large. {len(family['flavours'])} nuances couvrent {covered} accords "
            f"({_pct(covered / family['strict'])}) ; {family['other']['strict']} restent "
            "sans combinaison assez fréquente "
            f"(seuil : {family['min_support']} accords).",
            "",
        ]
        if family["constant"]:
            out += [
                "Présent dans presque tous les accords de la famille : "
                + ", ".join(c["label"] for c in family["constant"])
                + ".",
                "",
            ]
        out += [
            "| # | Nuance | Caractéristiques | Accords | Part (IC 95 %) | Large | Gabarits |",
            "|---|---|---|---|---|---|---|",
        ]
        for f in family["flavours"]:
            out.append(
                f"| {f['rank']} | {f.get('name') or '–'} | "
                + " + ".join(c["label"] for c in f["codes"])
                + f" | {f['strict']} | {_pct(f['share_of_family'])}{_ci(f['ci'])} | "
                f"{f['loose']} | {f['collapsed']} |"
            )
        other = family["other"]
        out += [
            f"| | Autres combinaisons | | {other['strict']} | "
            f"{_pct(other['share_of_family'])} | | |",
            "",
        ]
        for f in family["flavours"]:
            out += [
                f"### {f['rank']}. {f.get('name') or ' + '.join(c['label'] for c in f['codes'])}",
                "",
                f"{f['strict']} accords ({_pct(f['share_of_family'])} de la famille), "
                f"{f['collapsed']} gabarits distincts. Défini par : "
                + " + ".join(c["label"] for c in f["codes"])
                + ".",
                "",
            ]
            if f.get("description"):
                out += [f["description"], ""]
            if f.get("variations"):
                out += ["Variantes observées dans les extraits :", ""]
                out += [f"- {v}" for v in f["variations"]]
                out.append("")
            out += ["Répartition parmi ces accords (au moins 10 %) :", ""]
            out += _distribution_lines(f["distributions"])
            years = ", ".join(f"{y} : {n}" for y, n in f["years"].items())
            sectors = ", ".join(f"{s} ({n})" for s, n in f["top_sectors"])
            out += [
                "",
                f"Signatures par année : {years}.",
                f"Secteurs les plus fréquents : {sectors}.",
                "",
            ]
            for q in f.get("quotes", []):
                out += [
                    f"> {q['quote']}  ",
                    f"> — {q['company']}, {q['signed']} ([Légifrance]({q['url']}))",
                    "",
                ]
        if other["distributions"]:
            out += ["### Autres combinaisons", "", f"{other['strict']} accords :", ""]
            out += _distribution_lines(other["distributions"]) + [""]
    return "\n".join(out) + "\n"


def csv_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per agreement and family: the flavour it was placed in."""
    rows = []
    for name, family in result["families"].items():
        for f in family["flavours"]:
            rows += [
                {
                    "agreement_id": a,
                    "family": name,
                    "flavour": f["id"],
                    "flavour_name": f.get("name", ""),
                    "codes": " + ".join(c["item"] for c in f["codes"]),
                }
                for a in f["agreements"]
            ]
        rows += [
            {
                "agreement_id": a,
                "family": name,
                "flavour": f"{name}-other",
                "flavour_name": "Autres combinaisons",
                "codes": "",
            }
            for a in family["other"]["agreements"]
        ]
    return rows
