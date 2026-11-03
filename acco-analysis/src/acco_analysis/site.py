"""out/flavours.html: one self-contained local page (data embedded, nothing fetched) to
browse the flavours of each family and filter them by signature year and sector."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from acco_analysis.codebook import FAMILIES
from acco_analysis.corpus import Agreement
from acco_analysis.crypto_site import file_key

TEMPLATE = Path(__file__).with_name("flavours_site.html")


def placed_agreements(flavours: dict[str, Any]) -> list[str]:
    """Ids of the agreements placed in a flavour (or in a family's "other"), sorted."""
    return sorted(
        {
            a
            for fam in flavours["families"].values()
            for f in fam["flavours"]
            for a in f["agreements"]
        }
        | {
            a
            for fam in flavours["families"].values()
            for a in fam["other"]["agreements"]
        }
    )


def _section(passage_id: str) -> int:
    """Section index of a passage id `{agreement}-{section}[-{n}]`, -1 if unreadable."""
    parts = passage_id.split("-")
    return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else -1


def build_data(
    flavours: dict[str, Any],
    metrics: dict[str, Any],
    agreements: Sequence[Agreement],
    profiles: dict[str, dict[str, dict[str, Any]]],
    salt: bytes | None = None,
    report: bool = False,
) -> dict[str, Any]:
    """The data of the page: the flavours, and what the filters work on: for every
    agreement collected its year, sector and families (overview), and for those placed
    in a flavour also their template. With a `salt`, the agreements placed in a flavour
    also carry the key of their page (`accord.html?k=`); without, the page has no links
    to agreement pages."""
    strict_profiles = profiles["strict"]
    by_id = {a.id: a for a in agreements}
    used = placed_agreements(flavours)
    index = {a: i for i, a in enumerate(used)}
    sectors = sorted({a.sector or "" for a in agreements} - {""})
    sector_index = {s: i for i, s in enumerate(sectors)}
    units: dict[str, int] = {}
    rows = []
    for a in used:
        template = strict_profiles[a]["template"]
        unit = f"t{template}" if template is not None else a
        rows.append(
            [
                int((by_id[a].signed or "0000")[:4]),
                sector_index.get(by_id[a].sector or "", -1),
                units.setdefault(unit, len(units)),
                by_id[a].company,
                file_key(salt, a) if salt else "",
            ]
        )
    families = []
    for name, fam in flavours["families"].items():
        flavour_rows = []
        for f in fam["flavours"]:
            flavour_rows.append(
                {
                    **{
                        k: f.get(k)
                        for k in (
                            "id",
                            "rank",
                            "name",
                            "description",
                            "variations",
                            "strict",
                            "loose",
                            "collapsed",
                            "distributions",
                            "top_sectors",
                        )
                    },
                    "codes": [c["label"] for c in f["codes"]],
                    "members": [index[a] for a in f["agreements"]],
                    "quotes": [
                        {
                            "quote": q["quote"],
                            "company": q["company"],
                            "signed": q["signed"],
                            "url": q["url"],
                            "agreement": index.get(q["url"].rsplit("/", 1)[-1], -1),
                            "section": _section(q["id"]),
                        }
                        for q in f.get("quotes", [])
                    ],
                }
            )
        families.append(
            {
                "name": name,
                "label": fam["label"],
                "strict": fam["strict"],
                "loose": fam["loose"],
                "constant": [c["label"] for c in fam["constant"]],
                "min_support": fam["min_support"],
                "flavours": flavour_rows,
                "other": {
                    "members": [index[a] for a in fam["other"]["agreements"]],
                    "distributions": fam["other"]["distributions"],
                },
            }
        )
    family_bits = {name: bit for bit, name in enumerate(FAMILIES)}

    def mask(profile: dict[str, Any] | None) -> int:
        """Bit per family, and bit `len(FAMILIES)` for "has a heat clause"."""
        if profile is None:
            return 0
        return 1 << len(FAMILIES) | sum(
            1 << family_bits[f] for f in profile["families"] if f in family_bits
        )

    everyone = [
        [
            int((a.signed or "0000")[:4]),
            sector_index.get(a.sector or "", -1),
            mask(profiles["strict"].get(a.id)),
            mask(profiles["loose"].get(a.id)),
        ]
        for a in agreements
    ]
    d = metrics["dataset"]
    return {
        "snapshot": flavours.get("snapshot", ""),
        "report": report,  # the site has the analysis note (`report.html`)
        "dataset": {
            k: d[k]
            for k in (
                "passages_coded",
                "template_groups",
                "agreements_in_a_template",
            )
        },
        "sectors": sectors,
        "agreements": rows,  # [year, sector, template unit, company, page key]
        "all": everyone,
        "families": families,
    }


def render(data: dict[str, Any]) -> str:
    # "</script>" inside a quote must not end the script element
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    return TEMPLATE.read_text().replace("__DATA__", blob)
