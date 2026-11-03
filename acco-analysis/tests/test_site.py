import json

from acco_analysis.corpus import Agreement
from acco_analysis.site import build_data, render


def agreement(i: str, signed: str, sector: str | None) -> Agreement:
    return Agreement(
        id=i,
        title="",
        company=i,
        siret=None,
        sector=sector,
        idcc=None,
        nature="ACCORD",
        signed=signed,
    )


def sample():
    flavours = {
        "snapshot": "s",
        "families": {
            "telework": {
                "label": "Télétravail",
                "strict": 3,
                "loose": 4,
                "constant": [{"item": "measures:telework", "label": "télétravail"}],
                "min_support": 10,
                "flavours": [
                    {
                        "id": "telework-1",
                        "rank": 1,
                        "name": "N",
                        "description": "d",
                        "variations": [],
                        "strict": 2,
                        "loose": 3,
                        "collapsed": 1,
                        "distributions": {},
                        "top_sectors": [],
                        "codes": [{"item": "x:y", "label": "y"}],
                        "agreements": ["a", "b"],
                        "quotes": [
                            {
                                "id": "a-1",
                                "quote": "fin </script> du texte",
                                "company": "a",
                                "signed": "2021-01-01",
                                "url": "https://www.legifrance.gouv.fr/acco/id/a",
                            }
                        ],
                    }
                ],
                "other": {"agreements": ["c"], "distributions": {}},
            }
        },
    }
    metrics = {
        "dataset": {
            k: 1
            for k in (
                "collected",
                "with_heat_clause_strict",
                "with_heat_clause_loose",
                "without_heat_clause",
                "passages_coded",
                "template_groups",
                "agreements_in_a_template",
            )
        },
        "families": {
            "telework": {
                "label": "Télétravail",
                "strict": 3,
                "loose": 4,
                "share_strict": 0.5,
                "share_loose": 0.6,
            }
        },
        "by_year": {
            "2021": {
                "collected": 3,
                "items": {"families": {"telework": {"share_loose": 0.5}}},
            }
        },
    }
    agreements = [
        agreement("a", "2021-01-01", "Bâtiment"),
        agreement("b", "2022-01-01", None),
        agreement("c", "2023-01-01", "Bâtiment"),
    ]
    strict = {
        "a": {"template": 7, "families": ["telework"]},
        "b": {"template": 7, "families": ["telework", "hours"]},
        "c": {"template": None, "families": ["reference_or_other"]},
    }
    loose = {**strict, "d": {"template": None, "families": ["telework"]}}
    return (
        flavours,
        metrics,
        agreements + [agreement("d", "2021-05-01", "Bâtiment")],
        {"strict": strict, "loose": loose},
    )


def test_members_are_indices_with_year_sector_and_template():
    data = build_data(*sample())
    assert data["sectors"] == ["Bâtiment"]
    assert data["agreements"] == [
        [2021, 0, 0, "a", ""],
        [2022, -1, 0, "b", ""],
        [2023, 0, 1, "c", ""],
    ]  # a, b share a template; no page keys without a salt
    flavour = data["families"][0]["flavours"][0]
    assert flavour["members"] == [0, 1]
    assert flavour["quotes"][0]["agreement"] == 0
    assert flavour["quotes"][0]["section"] == 1  # from the passage id "a-1"
    assert data["families"][0]["other"]["members"] == [2]


def test_page_embeds_the_data_without_ending_the_script_early():
    page = render(build_data(*sample()))
    assert "__DATA__" not in page
    assert page.count("</script>") == 2  # the data block and the page script
    blob = page.split('id="data">')[1].split("</script>")[0].replace("<\\/", "</")
    assert json.loads(blob)["families"][0]["flavours"][0]["quotes"][0][
        "quote"
    ].startswith("fin </script>")


def test_page_keys_come_from_the_salt():
    data = build_data(*sample(), salt=b"salt")
    keys = [row[4] for row in data["agreements"]]
    assert all(len(k) == 16 for k in keys) and len(set(keys)) == 3
    assert keys == [row[4] for row in build_data(*sample(), salt=b"salt")["agreements"]]
    assert keys != [
        row[4] for row in build_data(*sample(), salt=b"other")["agreements"]
    ]
