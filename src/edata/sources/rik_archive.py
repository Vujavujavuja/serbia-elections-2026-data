"""RIK: result files for elections that are not on the JSON results endpoint.

2020 files are on the current site; 2012-2016 are on arhiva.rik.parlament.gov.rs. Every
linked result file (XLS, PDF, DOC) is stored. Spreadsheets are parsed cell by cell into one
long table, so nothing depends on guessing each file's layout.
"""
from __future__ import annotations

import io
import re
from urllib.parse import quote, unquote, urljoin

import xlrd
from lxml import html as lxml_html

from ..http import Fetcher
from ..store import RawStore
from ..tables import write_table
from ._common import provenance

NAME = "rik_archive"
DESCRIPTION = "RIK result files for older elections (per-station XLS for 2012-2020)"

PAGES = {
    "parliamentary_2020": "https://www.rik.parlament.gov.rs/tekst/9386/ukupni-rezultati-izbora-za-narodne-poslanike-narodne-skupstine-2020-godine.php",
    "parliamentary_2016": "https://arhiva.rik.parlament.gov.rs/izbori-za-narodne-poslanike-2016-rezultati.php",
    "parliamentary_2014": "https://arhiva.rik.parlament.gov.rs/arhiva-izbori-za-narodne-poslanike-2014.php",
    "parliamentary_2012": "https://arhiva.rik.parlament.gov.rs/arhiva-izbori-za-narodne-poslanike-2012.php",
    "presidential_2017": "https://arhiva.rik.parlament.gov.rs/izbori-za-predsednika-republike-2017.php",
}
FILE = re.compile(r"\.(xlsx?|pdf|docx?|zip)$", re.I)


def fetch(store: RawStore) -> None:
    fetcher = Fetcher(store, NAME, min_interval=1.0, timeout=300)
    have = {r["tags"].get("file_url") for r in store.manifest(NAME) if r["status"] == 200}
    for election, page in PAGES.items():
        _, content = fetcher.fetch(page, ext=".html", tags={"kind": "page", "election": election})
        doc = lxml_html.fromstring(content.decode("utf-8", "replace"))
        for link in doc.xpath("//a[@href]"):
            href = link.get("href").strip()
            if not FILE.search(href) or not re.search(r"rezultat|extfile", href, re.I):
                continue
            url = urljoin(page, quote(unquote(href), safe="/:%"))
            if url in have:
                continue
            have.add(url)
            fetcher.fetch(url, ext="." + href.rsplit(".", 1)[-1].lower(),
                          tags={"kind": "file", "election": election, "file_url": url,
                                "file_name": unquote(href.rsplit("/", 1)[-1]),
                                "link_text": " ".join(link.text_content().split())})
    fetcher.close()


def parse(store: RawStore) -> dict[str, int]:
    files, cells = [], []
    latest = store.latest(NAME, key=lambda r: r["tags"].get("file_url"))
    for url, r in latest.items():
        if r["tags"].get("kind") != "file":
            continue
        t = r["tags"]
        files.append({"election": t["election"], "file_name": t["file_name"], "link_text": t["link_text"],
                      "size": r["size"], "local_path": r["path"], **provenance(r)})
        if not t["file_name"].lower().endswith(".xls"):
            continue
        book = xlrd.open_workbook(file_contents=store.read(r))
        for sheet in book.sheets():
            for row in range(sheet.nrows):
                for col in range(sheet.ncols):
                    value = sheet.cell_value(row, col)
                    if value == "":
                        continue
                    cells.append({"election": t["election"], "file_name": t["file_name"],
                                  "sheet": sheet.name, "row": row, "col": col,
                                  "value": str(value), "raw_sha256": r["sha256"]})
    write_table(NAME, "files", files)
    write_table(NAME, "cells", cells)
    return {"files": len(files), "cells": len(cells)}
