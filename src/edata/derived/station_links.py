"""Link polling stations between two elections on the RIK results endpoint.

RIK assigns new station ids for every election, so stations are matched within the same
municipality. Stations are ordered by number in each election and the two sequences of
(normalised) names are aligned, the way a text diff aligns lines. This follows stations
through insertions and removals that shift every later number, even where several stations
share one venue name. The `rule` column says how each pair was made:

  number+name       same number and same name
  renumbered        same name at the aligned position, different number
  renamed           aligned one-to-one between matched neighbours, names at least 60% similar
  replaced          aligned one-to-one between matched neighbours, names less than 60% similar
                    (a new venue for the same slot, or a different station: not decidable from names)
  unmatched_a/b     present in only one election, or inside a stretch where the number of
                    stations changed and one-to-one alignment is not possible

Names are compared after normalising case, quotes, punctuation and spacing.
"""
from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

import duckdb

from ..store import DATA_ROOT
from ..tables import write_table

NAME = "station_links"
DESCRIPTION = "Polling stations matched between Parliamentary 2023 and Parliamentary 2026"
PAIRS = [("341140", "680072"), ("341143", "341140")]  # (earlier, later)
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

            seq_a = sorted(a.values(), key=lambda r: (int(r[5]) if r[5].isdigit() else 10**9, r[5]))
            seq_b = sorted(b.values(), key=lambda r: (int(r[5]) if r[5].isdigit() else 10**9, r[5]))
            names_a, names_b = [norm(r[6]) for r in seq_a], [norm(r[6]) for r in seq_b]
            matcher = SequenceMatcher(None, names_a, names_b, autojunk=False)
            for op, a0, a1, b0, b1 in matcher.get_opcodes():
                if op == "equal":
                    for ra, rb in zip(seq_a[a0:a1], seq_b[b0:b1]):
                        emit("number+name" if ra[5] == rb[5] else "renumbered", ra, rb, 1.0)
                elif op == "replace" and a1 - a0 == b1 - b0:
                    for ra, rb in zip(seq_a[a0:a1], seq_b[b0:b1]):
                        sim = round(SequenceMatcher(None, norm(ra[6]), norm(rb[6])).ratio(), 3)
                        emit("renamed" if sim >= 0.6 else "replaced", ra, rb, sim)
                else:
                    for ra in seq_a[a0:a1]:
                        emit("unmatched_a", ra, None)
                    for rb in seq_b[b0:b1]:
                        emit("unmatched_b", None, rb)
    write_table("derived", "station_links", rows)
    return {"station_links": len(rows)}
