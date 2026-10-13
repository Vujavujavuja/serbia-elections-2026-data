"""RIK: register of election-commission documents (https://www.rik.parlament.gov.rs/dokumenta/41985).

Listed through a JSON endpoint by election and document type: commission decisions, candidate
lists, polling-station decisions, polling-board appointments. The listing is always stored;
the PDF files themselves are downloaded for the document types named in `files`.
"""
from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import quote, unquote

from ..http import Fetcher
from ..store import RawStore
from ..tables import write_table
from ._common import provenance

NAME = "rik_documents"
DESCRIPTION = "RIK document register: polling-station decisions, candidate lists, commission decisions, polling boards"

BASE = "https://www.rik.parlament.gov.rs"
TYPES = {"1": "commission decisions", "2": "candidate lists", "3": "polling stations",
         "4": "polling board appointments", "5": "commission appointments"}


def fetch(store: RawStore, round: str = "680072", types: str = "1,2,3,4,5", files: str = "2,3",
          max_pages: str = "500") -> None:
    fetcher = Fetcher(store, NAME, min_interval=0.3, timeout=300,
                      headers={"X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/dokumenta/41985"})
    have = {r["tags"].get("file_url") for r in store.manifest(NAME) if r["status"] == 200}
    for doc_type in types.split(","):
        for page in range(1, int(max_pages) + 1):
            _, content = fetcher.fetch(
                f"{BASE}/get-additional-documents", ext=".json",
                query={"page": page, "filters[document-type]": doc_type,
                       "filters[election-round]": round, "filters[municipality-id]": 0},
                tags={"kind": "listing", "round": round, "doc_type": doc_type, "page": page})
            try:
                records = json.loads(content).get("records") or []
            except ValueError:
                records = []
            if not records:
                break
            if doc_type not in files.split(","):
                continue
            for record in records:
                for href in re.findall(r'href="([^"]+)"', " ".join(record.get("extfiles_link") or [])):
                    url = BASE + quote(unquote(unescape(href)), safe="/:%")
                    if url not in have:
                        have.add(url)
                        fetcher.fetch(url, ext="." + href.rsplit(".", 1)[-1].lower()[:5],
                                      tags={"kind": "file", "round": round, "doc_type": doc_type,
                                            "file_url": url})
    fetcher.close()


def parse(store: RawStore) -> dict[str, int]:
    local = {r["tags"]["file_url"]: r for r in store.manifest(NAME)
             if r["tags"].get("kind") == "file" and r["status"] == 200}
    listings = store.latest(NAME, key=lambda r: (r["tags"].get("kind"), r["tags"].get("round"),
                                                 r["tags"].get("doc_type"), r["tags"].get("page")))
    rows = []
    for key, r in listings.items():
        if key[0] != "listing":
            continue
        try:
            records = json.loads(store.read(r)).get("records") or []
        except ValueError:
            continue
        for record in records:
            hrefs = re.findall(r'href="([^"]+)"', " ".join(record.get("extfiles_link") or []))
            for href in hrefs or [None]:
                url = BASE + quote(unquote(unescape(href)), safe="/:%") if href else None
                got = local.get(url)
                rows.append({
                    "round_id": key[1], "doc_type": key[2], "doc_type_name": TYPES.get(key[2]),
                    **{k: v for k, v in record.items() if k != "extfiles_link"},
                    "published_at_unix": record.get("datetime"), "file_url": url,
                    "local_path": got["path"] if got else None,
                    "file_sha256": got["sha256"] if got else None, **provenance(r)})
    write_table(NAME, "documents", rows)
    return {"documents": len(rows)}
