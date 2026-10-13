"""THIRD PARTY, unofficial: 2026 polling stations with addresses and coordinates from
github.com/majstors/datasets-parlamentarni-izbori2026.

Per its README the station list was taken from izbori26.com on 29 Sep 2026 and geocoded by
the author; the geo_tacnost column states how precise each coordinate is.
"""
from __future__ import annotations

from ..store import RawStore
from ..tables import write_table
from ._common import fetch_github_files, latest_files, provenance, read_delimited

NAME = "thirdparty_majstors_stations"
DESCRIPTION = "UNOFFICIAL geocoded 2026 polling stations from github.com/majstors/datasets-parlamentarni-izbori2026"
REPO = "majstors/datasets-parlamentarni-izbori2026"
TABLES = {"biracka_mesta_par_2026.tsv": "stations", "izborne_komisije_par_2026.tsv": "commissions"}


def fetch(store: RawStore) -> None:
    fetch_github_files(store, NAME, REPO, lambda path: path.endswith((".tsv", ".md")))


def parse(store: RawStore) -> dict[str, int]:
    out = {}
    files = latest_files(store, NAME)
    for path, table in TABLES.items():
        rows = []
        if path in files:
            r = files[path]
            rows = [{**row, "repo_commit": r["tags"]["commit"], **provenance(r)}
                    for row in read_delimited(store.read(r), delimiter="\t")]
        write_table(NAME, table, rows)
        out[table] = len(rows)
    return out
