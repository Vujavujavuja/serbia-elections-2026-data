"""What RIK's correction rulings (Образац РГ-7) changed on polling-board records.

Input: the rulings downloaded by `rik_station_records` (doc=Решење) and the page text read by
`edata ocr`-style OCR into data/ocr/<sha>/0001.txt. Each ruling states, in one sentence,
which point of the record is corrected and the old and new number, e.g.
"у тачки 4. Записника број 2216 замењује бројем 2215". Point 11.5 changes carry the list
number ("под редним бројем 7").

Rows are one change each. `pattern` names the wording matched; rulings whose wording could
not be parsed are kept with pattern 'unparsed' and the clause text, so nothing is dropped.
OCR can misread digits: `clause` holds the text the numbers came from.
"""
from __future__ import annotations

import re

import duckdb

from ..store import DATA_ROOT
from ..tables import write_table

NAME = "ruling_changes"
DESCRIPTION = "Old and new values changed by RIK correction rulings, per station"

N = r"(\d{1,4}(?:\.\d{3})?)"
PATTERNS = [
    ("replaced_by", N + r"\s*(?:се\s*)?замењуј\w*\s*(?:се\s*)?бројем\s*" + N),
    ("instead_of", r"уместо\s+(?:броја\s*)?[„\"]?" + N + r"[^\d]{0,15}?упис\w*\s*(?:се\s*)?(?:број\s*)?" + N),
    ("changed_to", N + r"\s*(?:се\s*)?мења\s*(?:се\s*)?у\s*(?:број[^\d]{0,60})?" + N),
    ("blank_filled", r"()празн\w*\s+рубрик\w*\s*(?:се\s*)?упис\w*\s*(?:се\s*)?број\s*" + N),
]


def _num(s: str) -> int:
    return int(s.replace(".", "")) if s else 0  # an empty cell on the record counts as 0


def build() -> dict[str, int]:
    con = duckdb.connect()
    p = f"{DATA_ROOT}/parsed"
    docs = con.execute(f"""
        SELECT f.round_id, f.station_id, f.doc_type, f.raw_sha256, f.source_url,
               s.municipality_name, s.station_no, s.station_name
        FROM read_parquet('{p}/rik_station_records/files.parquet') f
        JOIN read_parquet('{p}/rik_results/stations.parquet') s USING (round_id, station_id)
        WHERE f.doc_type LIKE 'Решење о исправљању%'""").fetchall()
    rows = []
    for rnd, sid, dtype, sha, url, mun, no, name in docs:
        page = DATA_ROOT / "ocr" / sha / "0001.txt"
        if not page.exists():
            continue
        text = " ".join(page.read_text().split())
        m = re.search(r"тако\s+(?:што|да)(.{0,1200}?)(?:у\s+складу\s+с|$)", text, re.I)
        clause = m.group(1) if m else ""
        base = {"round_id": rnd, "station_id": sid, "municipality_name": mun, "station_no": no,
                "station_name": name, "doc_type": dtype, "ruling_url": url, "ruling_sha256": sha}
        found = False
        current_point = None
        # split into segments at each mention of a point ("тачки 11.4") or list number
        for seg in re.split(r"(?=\bу?\s*тачк\w*\s*\d)|(?=\bу?\s*подтачк\w*\s*\d)|(?=под\s+редним\s+бројем)|(?=редни\s+број)", clause):
            point = re.search(r"(?<!под)тачк\w*\s*(\d{1,2}(?:\.\d{1,2})?)", seg)
            if point:
                current_point = point.group(1).rstrip(".")
            lst = re.search(r"(?:редн\w*\s+број\w*|подтачк\w*)\s*(\d{1,2})", seg)
            for pname, pat in PATTERNS:
                for old, new in re.findall(pat, seg, re.I):
                    if re.search(re.escape(old) + r"\s*\+", seg) or re.search(r"\+\s*" + re.escape(old) + r"\b", seg):
                        continue  # "1292+1 замењују бројем 1293": a sum, not an old value
                    found = True
                    rows.append({**base, "point": current_point,
                                 "list_no": int(lst.group(1)) if lst else None,
                                 "old": _num(old), "new": _num(new), "delta": _num(new) - _num(old),
                                 "pattern": pname, "clause": seg.strip()[:300]})
        if not found:
            rows.append({**base, "point": None, "list_no": None, "old": None, "new": None, "delta": None,
                         "pattern": "unparsed" if clause else "no_clause", "clause": (clause or text[:300])[:300]})
    write_table("derived", NAME, rows)
    return {NAME: len(rows)}
