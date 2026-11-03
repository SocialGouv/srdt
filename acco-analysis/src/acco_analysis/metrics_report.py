"""out/metrics.md and the flat CSV tables, from the figures of metrics.build."""

from typing import Any

from acco_analysis.codebook import FAMILIES, NO_FAMILY
from acco_analysis.metrics import FAMILY_NAMES, LABELS

DIMENSION_TITLES = {
    "measures": "Mesures",
    "triggers": "Déclencheurs",
    "initiative": "Initiative",
    "scope": "Public concerné",
    "pay": "Effet sur la rémunération",
    "procedure": "Procédure",
    "strength": "Portée de la clause",
}
TOP_IN_FAMILY = 8
TOP_PAIRS = 15


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.1f} %"


def _range(strict: float | None, loose: float | None) -> str:
    if strict is None or loose is None:
        return "–"
    low, high = sorted((strict, loose))
    return f"{low * 100:.1f} à {high * 100:.1f} %"


def _ci(ci: list[float] | tuple[float, float] | None) -> str:
    return "–" if ci is None else f"{ci[0] * 100:.1f}–{ci[1] * 100:.1f}"


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    out = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return [*out, ""]


def _code_rows(codes: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for code, c in sorted(codes.items(), key=lambda x: -x[1]["loose"]):
        rows.append(
            [
                c["label"],
                f"`{code}`",
                c["strict"],
                c["loose"],
                _range(c["share_strict"], c["share_loose"]),
                f"{_ci(c['ci_strict'])} / {_ci(c['ci_loose'])}",
                c["collapsed_loose"],
                "oui" if c["model_dependent"] else "",
            ]
        )
    return rows


CODE_HEADERS = [
    "Valeur",
    "Code",
    "Accords (strict)",
    "Accords (large)",
    "Part des accords avec clause chaleur",
    "IC 95 % strict / large (points)",
    "Modèles collapsés (large)",
    "Dépend du modèle",
]


def to_markdown(m: dict[str, Any]) -> str:
    d = m["dataset"]
    out = [
        "# Clauses chaleur des accords d'entreprise : chiffres",
        "",
        f"Snapshot `{m['snapshot']}`. Généré par `acco-analysis metrics`.",
        "",
        "## Comment lire",
        "",
        "- **L'unité est l'accord**, jamais l'extrait : un accord avec trois extraits "
        "compte une fois.",
        "- **Deux lectures de chaque chiffre.** *Strict* : les deux modèles "
        "(mistral-medium-3-5 et gemma-4-31b-it) donnent le code. *Large* : au moins un "
        "des deux le donne. L'écart mesure le désaccord des modèles ; « dépend du "
        "modèle » signale un code dont le strict est sous "
        f"{int(0.6 * 100)} % du large. Aucun codage n'est validé à la main à ce stade.",
        f"- **Dénominateur** : les {m['n_heat']} accords qui ont une clause chaleur "
        f"(lecture large) ; les parts sur les {m['n_collected']} accords collectés "
        "sont dans le JSON. L'intervalle de confiance est celui de Wilson à 95 %.",
        "- **Portée** : les accords ont été collectés sur des termes liés à la chaleur et "
        "l'extraction ne lit que le texte autour de « canicule », « chaleur » et "
        "variantes. Ces chiffres décrivent les entreprises qui encadrent la chaleur, "
        "pas les entreprises françaises, et ce sont des planchers (« températures "
        "élevées » seul est manqué).",
        "- Les accords d'un même modèle de clause (gabarit) comptent chacun ; la "
        "colonne « collapsés » compte un gabarit une seule fois.",
        "",
        "## Le corpus",
        "",
    ]
    out += _table(
        ["", "Valeur"],
        [
            ["Accords collectés", d["collected"]],
            ["Années de signature", f"{d['years'][0]} à {d['years'][-1]}"],
            ["Avec un extrait conservé par le filtre", d["kept_passages_agreements"]],
            [
                "Avec une clause chaleur (strict / large)",
                f"{d['with_heat_clause_strict']} / {d['with_heat_clause_loose']}",
            ],
            ["Sans clause chaleur", d["without_heat_clause"]],
            ["Extraits codés", d["passages_coded"]],
            [
                "Extraits qui parlent de chaleur (strict / large)",
                f"{d['passages_about_heat_strict']} / {d['passages_about_heat_loose']}",
            ],
            ["Extraits sans mesure (large)", d["passages_without_measure_loose"]],
            [
                "Textes tronqués parmi les accords avec clause",
                d["truncated_texts_with_heat"],
            ],
            [
                "Autres sources (docx, odt)",
                ", ".join(f"{k} : {v}" for k, v in d["other_sources_with_heat"].items())
                or "aucune",
            ],
            [
                "Gabarits (clauses communes à plusieurs accords)",
                f"{d['template_groups']} groupes, le plus grand sur "
                f"{d['template_largest_group_agreements']} accords",
            ],
            [
                "Accords dans un gabarit",
                f"{d['agreements_in_a_template']} ({_pct(d['template_share_of_heat'])})",
            ],
        ],
    )

    out += [
        "## Familles",
        "",
        "Une famille est une vue sur les mesures codées ; un accord "
        "peut être dans plusieurs.",
        "",
    ]
    rows = []
    for name in FAMILY_NAMES:
        f = m["families"].get(name)
        if f:
            rows.append(
                [
                    f["label"]
                    + (
                        " (résiduel : sans mesure retenue)" if name == NO_FAMILY else ""
                    ),
                    f["strict"],
                    f["loose"],
                    _range(f["share_strict"], f["share_loose"]),
                    f"{_ci(f['ci_strict'])} / {_ci(f['ci_loose'])}",
                    f["collapsed_loose"],
                    "oui" if f["model_dependent"] else "",
                ]
            )
    out += _table(
        [
            "Famille",
            "Accords (strict)",
            "Accords (large)",
            "Part des accords avec clause chaleur",
            "IC 95 % strict / large",
            "Gabarits collapsés (large)",
            "Dépend du modèle",
        ],
        rows,
    )

    for name in FAMILY_NAMES:
        f = m["families"].get(name)
        if not f or name == NO_FAMILY:
            continue
        out += [
            f"### {f['label']}",
            "",
            f"{f['loose']} accords (lecture large). "
            "Répartition des valeurs parmi ces accords :",
            "",
        ]
        for dimension, title in DIMENSION_TITLES.items():
            codes = f["dimensions"][dimension]
            rows = [
                [
                    c["label"],
                    c["strict"],
                    c["loose"],
                    _range(c["share_strict"], c["share_loose"]),
                ]
                for _, c in sorted(codes.items(), key=lambda x: -x[1]["loose"])[
                    :TOP_IN_FAMILY
                ]
            ]
            if rows:
                out += [f"**{title}**", ""]
                out += _table(["Valeur", "Strict", "Large", "Part de la famille"], rows)

    out += ["## Toutes les valeurs", ""]
    for dimension, title in DIMENSION_TITLES.items():
        out += [f"### {title}", ""]
        out += _table(CODE_HEADERS, _code_rows(m["dimensions"][dimension]))

    out += [
        "## Par année de signature",
        "",
        "Part (lecture large) des accords collectés cette année-là. Moins de 10 "
        "accords : pas de pourcentage. 2026 est une année partielle.",
        "",
    ]
    names = [n for n in FAMILY_NAMES if n in m["families"]]
    out += _table(
        ["Année", "Collectés", "Avec clause", *[LABELS["families"][n] for n in names]],
        [
            [
                year,
                g["collected"],
                g["with_heat_loose"],
                *[
                    _pct(g["items"]["families"][n]["share_loose"])
                    if n in g["items"]["families"]
                    else "–"
                    for n in names
                ],
            ]
            for year, g in m["by_year"].items()
        ],
    )
    for key, title in (
        ("by_sector", "Par secteur (15 plus gros)"),
        ("by_idcc", "Par IDCC (15 plus gros)"),
    ):
        out += [f"## {title}", ""]
        out += _table(
            [
                "Groupe",
                "Collectés",
                "Avec clause",
                *[LABELS["families"][n] for n in names],
            ],
            [
                [
                    name,
                    g["collected"],
                    g["with_heat_loose"],
                    *[
                        _pct(g["items"]["families"][n]["share_loose"])
                        if n in g["items"]["families"]
                        else "–"
                        for n in names
                    ],
                ]
                for name, g in m[key].items()
            ],
        )

    out += [
        "## Ce qui va ensemble",
        "",
        "Accords qui ont les deux valeurs. Jaccard : recouvrement rapporté à "
        "l'union des deux groupes. Lift : combien de fois plus souvent que si les "
        "deux étaient indépendants.",
        "",
    ]
    for key, title in (
        ("measures_measures", "Mesure × mesure"),
        ("triggers_measures", "Déclencheur × mesure"),
        ("triggers_pay", "Déclencheur × rémunération"),
        ("measures_pay", "Mesure × rémunération"),
    ):
        out += [f"### {title}", ""]
        out += _table(
            ["A", "B", "Strict", "Large", "Jaccard", "Lift"],
            [
                [
                    p["a_label"],
                    p["b_label"],
                    p["strict"],
                    p["loose"],
                    p["jaccard"],
                    p["lift"],
                ]
                for p in m["cooccurrence"][key][:TOP_PAIRS]
            ],
        )
    out += ["### Accords présents dans deux familles (lecture large)", ""]
    matrix = m["cooccurrence"]["families"]["loose"]
    out += _table(
        ["", *[LABELS["families"][n] for n in names]],
        [[LABELS["families"][a], *[matrix[a][b] for b in names]] for a in names],
    )

    out += [
        "## Chiffres cités dans les clauses (lecture large)",
        "",
        "Valeurs lues par les modèles ; seules celles qui sont un nombre seul sont "
        "regroupées, le reste est compté sans être deviné.",
        "",
    ]
    for kind, q in m["quantities"].items():
        if not q["agreements"]:
            continue
        out += [
            f"### `{kind}` : {q['agreements']} accords, {q['distinct_values']} valeurs distinctes",
            "",
        ]
        if "thresholds" in q:
            out += [
                "Seuils (°C, entre 15 et 60), accords par valeur : "
                + ", ".join(f"{k} °C : {v}" for k, v in q["thresholds"].items()),
                "",
            ]
        if "buckets_minutes" in q:
            out += [
                "Durées en minutes, accords par tranche : "
                + ", ".join(f"{k} : {v}" for k, v in q["buckets_minutes"].items())
                + ".",
                "",
            ]
        out += [
            "Valeurs les plus fréquentes : "
            + ", ".join(f"« {v} » ({n})" for v, n in q["top_values"]),
            "",
        ]

    out += [
        "## Anciens clusters et familles",
        "",
        "Extraits qui parlent de chaleur (lecture large) de chaque cluster k-means, "
        "répartis dans les familles par mesure.",
        "",
    ]
    rows = []
    for cluster, c in m["clusters"].items():
        rows.append(
            [
                cluster,
                c["passages"],
                c["heat"],
                *[c["families"].get(n, 0) for n in FAMILIES],
                c["families"].get(NO_FAMILY, 0),
            ]
        )
    out += _table(
        [
            "Cluster",
            "Extraits",
            "Chaleur",
            *[LABELS["families"][n] for n in FAMILIES],
            LABELS["families"][NO_FAMILY],
        ],
        rows,
    )

    out += ["## Contrôles de cohérence", ""]
    out += (
        [f"- {p}" for p in m["problems"]]
        if m["problems"]
        else ["Aucune incohérence détectée."]
    )
    return "\n".join(out) + "\n"


def csv_tables(m: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """{file name: rows} of the flat tables."""
    codes = []
    for dimension, values in m["dimensions"].items():
        for code, c in values.items():
            codes.append(
                {
                    "dimension": dimension,
                    "code": code,
                    "label": c["label"],
                    "strict": c["strict"],
                    "loose": c["loose"],
                    "share_strict": c["share_strict"],
                    "share_loose": c["share_loose"],
                    "ci_strict_low": (c["ci_strict"] or [None, None])[0],
                    "ci_strict_high": (c["ci_strict"] or [None, None])[1],
                    "ci_loose_low": (c["ci_loose"] or [None, None])[0],
                    "ci_loose_high": (c["ci_loose"] or [None, None])[1],
                    "share_collected_strict": c["share_collected_strict"],
                    "share_collected_loose": c["share_collected_loose"],
                    "passages_strict": c["passages_strict"],
                    "passages_loose": c["passages_loose"],
                    "verified_share": c["verified_share"],
                    "collapsed_strict": c["collapsed_strict"],
                    "collapsed_loose": c["collapsed_loose"],
                    "model_dependent": c["model_dependent"],
                }
            )
    tables: dict[str, list[dict[str, Any]]] = {"metrics_codes.csv": codes}
    for key, file in (
        ("by_year", "metrics_by_year.csv"),
        ("by_sector", "metrics_by_sector.csv"),
        ("by_idcc", "metrics_by_idcc.csv"),
    ):
        tables[file] = [
            {
                "group": name,
                "collected": g["collected"],
                "with_heat_loose": g["with_heat_loose"],
                "dimension": dimension,
                "code": code,
                **cell,
            }
            for name, g in m[key].items()
            for dimension, values in g["items"].items()
            for code, cell in values.items()
        ]
    tables["metrics_cooccurrence.csv"] = [
        {"table": key, **pair}
        for key, pairs in m["cooccurrence"].items()
        if key != "families"
        for pair in pairs
    ]
    return tables
