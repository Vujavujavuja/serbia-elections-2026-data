"""THIRD PARTY, unofficial: weekly copies of the ministry's voter register tables kept by
github.com/nemdub/promene-biracki-spisak since February 2026.

The ministry does not publish history, so this is the only source for weeks before our
own collection started. It is someone else's scrape and is stored as such (origin column).
"""
from __future__ import annotations

from ..store import RawStore
from ..tables import write_table
from ._common import fetch_github_files, latest_files, provenance, read_delimited

NAME = "thirdparty_nemdub_register"
DESCRIPTION = "UNOFFICIAL weekly voter register history from github.com/nemdub/promene-biracki-spisak"
REPO = "nemdub/promene-biracki-spisak"


def fetch(store: RawStore) -> None:
    fetch_github_files(store, NAME, REPO, lambda path: path.startswith("data/") or path.endswith(".md"))


def parse(store: RawStore) -> dict[str, int]:
    tables: dict[str, list[dict]] = {"counts": [], "changes": [], "summary": []}
    for path, r in sorted(latest_files(store, NAME).items()):
        name = path.rsplit("/", 1)[-1]
        table = ("counts" if name.startswith("biraci_") else "changes" if name.startswith("promene_")
                 else "summary" if name == "summary.csv" else None)
        if table is None:
            continue
        for row in read_delimited(store.read(r)):
            tables[table].append({**row, "file": path, "repo_commit": r["tags"]["commit"],
                                  "repo_commit_date": r["tags"]["commit_date"], **provenance(r)})
    for table, rows in tables.items():
        write_table(NAME, table, rows)
    return {table: len(rows) for table, rows in tables.items()}
