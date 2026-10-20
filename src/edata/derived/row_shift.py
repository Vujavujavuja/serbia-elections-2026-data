"""Search published station results for votes written against the wrong list (row shifts).

A polling board fills the votes per list in a fixed column of rows. If it writes them one row
off, or swaps two neighbouring rows, list k's votes are published for list k±1. Such a
station's vote vector then looks like its municipality's usual vector shifted by one row.

For each station, the expected shares are its municipality's shares from all *other*
stations. The score is how much more likely the published votes are under the best
shifted/swapped arrangement than as published (log-likelihood ratio, multinomial).
Arrangements tested: every adjacent swap (k, k+1), and every block shift (all rows from k
downward moved one row up or down). A high score is a candidate, not a finding: the scanned
record must be checked, and some places genuinely vote very differently from their
municipality (e.g. minority villages).
"""
from __future__ import annotations

import duckdb
import numpy as np

from ..store import DATA_ROOT
from ..tables import write_table

NAME = "row_shift"
DESCRIPTION = "Stations whose votes look like the municipality's pattern shifted by one list row"
ROUNDS = ("341140", "341143", "567956")


def _arrangements(n):
    """(label, index map) where expected share for row i is taken from row map[i]."""
    base = np.arange(n)
    for k in range(n - 1):
        m = base.copy(); m[k], m[k + 1] = k + 1, k
        yield f"swap {k + 1}<->{k + 2}", m
    for k in range(1, n):
        m = base.copy(); m[k:] = base[k - 1:-1]; m[k - 1] = -1  # rows k.. took the row above's votes
        yield f"shift down from {k + 1}", m
        m = base.copy(); m[k - 1:-1] = base[k:]; m[-1] = -1     # rows k.. took the row below's votes
        yield f"shift up from {k}", m


def build() -> dict[str, int]:
    con = duckdb.connect()
    p = f"{DATA_ROOT}/parsed/rik_results"
    out = []
    for rnd in ROUNDS:
        rows = con.execute(f"""
            SELECT s.municipality_name, s.station_id, s.station_no, s.station_name, r.count_number, r.votes
            FROM read_parquet('{p}/stations.parquet') s
            JOIN read_parquet('{p}/station_results.parquet') r USING (round_id, station_id)
            WHERE s.round_id = ? AND s.region_id IN ('1','2','3','4')
            ORDER BY 1, 2, 5""", [rnd]).fetchall()
        lists = sorted({r[4] for r in rows}); idx = {c: i for i, c in enumerate(lists)}; n = len(lists)
        stations = {}
        for mun, sid, no, name, cn, v in rows:
            st = stations.setdefault(sid, {"mun": mun, "no": no, "name": name, "v": np.zeros(n)})
            st["v"][idx[cn]] = v or 0
        muni_tot = {}
        for st in stations.values():
            muni_tot[st["mun"]] = muni_tot.get(st["mun"], np.zeros(n)) + st["v"]
        arr = list(_arrangements(n))
        for sid, st in stations.items():
            v = st["v"]; total = v.sum()
            if total < 50:
                continue
            rest = muni_tot[st["mun"]] - v
            if rest.sum() < 200:
                continue
            q = (rest + 0.5) / (rest.sum() + 0.5 * n)          # smoothed municipal shares
            base_ll = float((v * np.log(q)).sum())
            best = (0.0, None)
            for label, m in arr:
                qa = np.where(m >= 0, q[np.clip(m, 0, n - 1)], 0.5 / (rest.sum() + 0.5 * n))
                qa = qa / qa.sum()
                ll = float((v * np.log(qa)).sum())
                if ll - base_ll > best[0]:
                    best = (ll - base_ll, label)
            if best[1] is None:
                continue
            share = v / total
            # deviance per vote, as published and after undoing the best arrangement:
            # a real row shift looks ordinary once undone; a village that simply votes
            # differently still looks unusual
            m = dict(arr)[best[1]]
            qa = np.where(m >= 0, q[np.clip(m, 0, n - 1)], 0.5 / (rest.sum() + 0.5 * n)); qa = qa / qa.sum()
            nz = v > 0
            g2_base = float(2 * (v[nz] * np.log(v[nz] / (total * q[nz]))).sum()) / total
            g2_alt = float(2 * (v[nz] * np.log(v[nz] / (total * qa[nz]))).sum()) / total
            out.append({"round_id": rnd, "station_id": sid, "municipality_name": st["mun"],
                        "station_no": st["no"], "station_name": st["name"], "votes_total": int(total),
                        "best_arrangement": best[1], "llr": round(best[0], 2),
                        "llr_per_vote": round(best[0] / total, 4),
                        "deviance_per_vote": round(g2_base, 4), "deviance_after_undo": round(g2_alt, 4),
                        "station_shares": ",".join(f"{x:.3f}" for x in share),
                        "municipal_shares": ",".join(f"{x:.3f}" for x in q),
                        "list_order": ",".join(str(c) for c in lists)})
    write_table("derived", NAME, out)
    return {NAME: len(out)}
