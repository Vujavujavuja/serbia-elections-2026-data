"""RIK: scanned polling-board records and related rulings, per polling station (PDF).

The links come from the per-station responses already collected by `rik_results`
(table rik_results/station_documents); run that collector first. There are tens of
thousands of files, so this one only downloads what `select` asks for:

  select=gap:N        stations where published "voted" exceeds ballots counted by N or more
  select=ids:1,2,3    specific RIK station ids
  select=all          every station of the round
"""
from __future__ import annotations

from urllib.parse import quote, unquote

import duckdb

from ..http import Fetcher
from ..store import DATA_ROOT, RawStore
from ..tables import write_table
from ._common import provenance

NAME = "rik_station_records"
DESCRIPTION = "Scanned polling-board records (PDF) for selected stations; needs rik_results first"
BASE = "https://www.rik.parlament.gov.rs"


def fetch(store: RawStore, round: str = "341140", select: str = "gap:10") -> None:
    con = duckdb.connect()
    parsed = f"{DATA_ROOT}/parsed/rik_results"
    kind, _, arg = select.partition(":")
    if kind == "gap":
        where = f"""station_id IN (SELECT station_id FROM read_parquet('{parsed}/station_summary.parquet')
                    WHERE round_id = '{round}'
                      AND turnout_value_1 - (ballots_value_0 + ballots_value_1) >= {int(arg)})"""
    elif kind == "ids":
        where = "station_id IN (" + ",".join(f"'{int(i)}'" for i in arg.split(",")) + ")"
    else:
        where = "TRUE"
    docs = con.execute(f"""SELECT DISTINCT station_id, doc_type, file_name, href, uploaded_at
                           FROM read_parquet('{parsed}/station_documents.parquet')
                           WHERE round_id = ? AND {where}""", [round]).fetchall()
    have = {r["tags"].get("href") for r in store.manifest(NAME) if r["status"] == 200}
    fetcher = Fetcher(store, NAME, min_interval=0.5, timeout=300)
    for station_id, doc_type, file_name, href, uploaded_at in docs:
        if href in have:
            continue
        fetcher.fetch(BASE + quote(unquote(href), safe="/:%@"), ext=".pdf",
                      tags={"round": round, "station": station_id, "doc_type": doc_type,
                            "file_name": file_name, "href": href, "uploaded_at": uploaded_at})
    fetcher.close()
    print(f"{NAME}: {len(docs)} documents selected")


def parse(store: RawStore) -> dict[str, int]:
    rows = [{"round_id": r["tags"]["round"], "station_id": r["tags"]["station"],
             "doc_type": r["tags"]["doc_type"], "file_name": r["tags"]["file_name"],
             "uploaded_at": r["tags"]["uploaded_at"], "size": r["size"], "local_path": r["path"],
             **provenance(r)}
            for r in store.latest(NAME, key=lambda r: r["tags"].get("href")).values()]
    write_table(NAME, "files", rows)
    return {"files": len(rows)}
