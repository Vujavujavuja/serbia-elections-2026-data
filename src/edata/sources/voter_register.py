"""Ministry of Public Administration (MDULS): open tables of the Unified Voter Register.

Two pages on https://upit.birackispisak.gov.rs need no login:
  /PregledBrojaBiraca  voters per municipality on a stated date
  /BrojPromena         register changes per municipality by legal basis, for a stated week
The ministry overwrites both, so history exists only if they are collected repeatedly.
"""
from __future__ import annotations

import re

from lxml import html as lxml_html

from ..http import Fetcher
from ..store import RawStore
from ..tables import write_table
from ._common import provenance

NAME = "voter_register"
DESCRIPTION = "Voter counts and register changes per municipality (upit.birackispisak.gov.rs open tables)"

BASE = "https://upit.birackispisak.gov.rs"
PAGES = ("PregledBrojaBiraca", "BrojPromena")
DATE = r"(\d{2}\.\d{2}\.\d{4})"


def fetch(store: RawStore) -> None:
    fetcher = Fetcher(store, NAME, min_interval=1.0)
    fetcher.client.get(f"{BASE}/")  # the site issues a cookie on the front page
    for page in PAGES:
        fetcher.fetch(f"{BASE}/{page}", ext=".html", tags={"page": page})
    fetcher.close()


def _rows(content: bytes) -> tuple[str, list[list[str]]]:
    doc = lxml_html.fromstring(content.decode("utf-8", "replace"))
    for bad in doc.xpath("//script|//style"):
        bad.drop_tree()
    text = " ".join(doc.text_content().split())
    rows = []
    for tr in doc.xpath("//table//tr"):
        cells = [" ".join(td.text_content().split()) for td in tr.xpath("./td")]
        if cells:
            rows.append(cells)
    return text, rows


def parse(store: RawStore) -> dict[str, int]:
    counts, changes, seen = [], [], set()
    for r in store.manifest(NAME):
        page = r["tags"].get("page")
        if r["status"] != 200 or (page, r["sha256"]) in seen:
            continue  # identical bytes already parsed; the manifest still records each fetch
        seen.add((page, r["sha256"]))
        text, rows = _rows(store.read(r))
        if page == "PregledBrojaBiraca":
            m = re.search(r"НА ДАН\s*" + DATE, text, flags=re.I)
            for cells in rows:
                counts.append({"as_of": m.group(1) if m else None, "municipality": cells[0],
                               "voters_raw": cells[1], "voters": int(cells[1]) if cells[1].isdigit() else None,
                               **provenance(r)})
        elif page == "BrojPromena":
            m = re.search(DATE + r"\.?\s*ДО\s*" + DATE, text, flags=re.I)
            for cells in rows:
                changes.append({"period_from": m.group(1) if m else None,
                                "period_to": m.group(2) if m else None,
                                "municipality": cells[0], "change_type": cells[1], "changes_raw": cells[2],
                                "changes": int(cells[2]) if cells[2].isdigit() else None, **provenance(r)})
    write_table(NAME, "counts", counts)
    write_table(NAME, "changes", changes)
    return {"counts": len(counts), "changes": len(changes)}
