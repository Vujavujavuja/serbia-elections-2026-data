"""Link polling stations between two elections on the RIK results endpoint.

RIK assigns new station ids for every election, so stations are matched within the same
municipality by station number and name. The `rule` column says how each pair was made:

  number+name      same number, same name after normalising case, quotes and spacing
  number+similar   same number, names at least 60% similar
  name_renumbered  different number, identical normalised name that is unique in the
                   municipality in both elections
  number_only      same number, names less than 60% similar (may be a different place)
  unmatched_a/b    present in only one of the two elections
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

import duckdb

from ..store import DATA_ROOT
from ..tables import write_table

NAME = "station_links"
DESCRIPTION = "Polling stations matched between Parliamentary 2023 and Parliamentary 2026"
PAIRS = [("341140", "680072")]
COLUMNS = "region_id, municipality_id, municipality_code, municipality_name, station_id, station_no, station_name"


def norm(name: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", name.upper()).split())


def build() -> dict[str, int]:
    con = duckdb.connect()
    stations = f"read_parquet('{DATA_ROOT}/parsed/rik_results/stations.parquet')"
    rows = []
    for round_a, round_b in PAIRS:
        def load(round_id):
            out = defaultdict(dict)
            for r in con.execute(f"SELECT {COLUMNS} FROM {stations} WHERE round_id = ?", [round_id]).fetchall():
                out[(r[0], r[1])][r[5]] = r
            return out
        a_all, b_all = load(round_a), load(round_b)
        for muni in sorted(set(a_all) | set(b_all)):
            a, b = dict(a_all.get(muni, {})), dict(b_all.get(muni, {}))

            def emit(rule, ra, rb, similarity=None):
                ref = ra or rb
                rows.append({
                    "round_a": round_a, "round_b": round_b, "rule": rule, "name_similarity": similarity,
                    "region_id": ref[0], "municipality_id": ref[1], "municipality_code": ref[2],
                    "municipality_name": ref[3],
                    "station_id_a": ra[4] if ra else None, "station_no_a": ra[5] if ra else None,
                    "station_name_a": ra[6] if ra else None,
                    "station_id_b": rb[4] if rb else None, "station_no_b": rb[5] if rb else None,
                    "station_name_b": rb[6] if rb else None})

            weak = []
            for no in sorted(set(a) & set(b)):
                na, nb = norm(a[no][6]), norm(b[no][6])
                sim = round(SequenceMatcher(None, na, nb).ratio(), 3)
                if na == nb:
                    emit("number+name", a.pop(no), b.pop(no), 1.0)
                elif sim >= 0.6:
                    emit("number+similar", a.pop(no), b.pop(no), sim)
                else:
                    weak.append((no, sim))
            # among what is left (including weak same-number pairs), look for renumbered stations
            count_a = Counter(norm(r[6]) for r in a_all.get(muni, {}).values())
            count_b = Counter(norm(r[6]) for r in b_all.get(muni, {}).values())
            by_name_b = {norm(r[6]): no for no, r in b.items()}
            for no_a in sorted(a):
                key = norm(a[no_a][6])
                no_b = by_name_b.get(key)
                if no_b is not None and no_b in b and no_b != no_a and count_a[key] == 1 and count_b[key] == 1:
                    emit("name_renumbered", a.pop(no_a), b.pop(no_b), 1.0)
            for no, sim in weak:
                if no in a and no in b:
                    emit("number_only", a.pop(no), b.pop(no), sim)
            for no in sorted(a):
                emit("unmatched_a", a[no], None)
            for no in sorted(b):
                emit("unmatched_b", None, b[no])
    write_table("derived", "station_links", rows)
    return {"station_links": len(rows)}
