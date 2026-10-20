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
ROUNDS = ("341140", "341143", "567956", "680072")


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
    pairs = _neighbour_pairs(con, p)
    _compare_with_previous(con, p, pairs)
    write_table("derived", "row_shift_pairs", pairs)
    return {NAME: len(out), "row_shift_pairs": len(pairs)}


def _neighbour_pairs(con, p: str) -> list[dict]:
    """The simpler rule that found every confirmed 2023 case: list k (almost) empty where the
    municipality predicts 6+ votes, while the neighbouring row holds about that many extra
    and is not itself a list expected to be strong there."""
    rows = []
    for rnd in ROUNDS:
        rows += con.execute(f"""
            WITH v AS (SELECT s.municipality_name m, s.station_id sid, s.station_no sno, r.count_number l,
                              coalesce(r.votes, 0) v
                       FROM read_parquet('{p}/stations.parquet') s
                       JOIN read_parquet('{p}/station_results.parquet') r USING (round_id, station_id)
                       WHERE s.round_id = ? AND s.region_id IN ('1','2','3','4')
                       QUALIFY r.raw_sha256 = last_value(r.raw_sha256) OVER (
                           PARTITION BY r.station_id ORDER BY r.last_fetched_at
                           ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)),
            t AS (SELECT sid, sum(v) tot FROM v GROUP BY 1),
            mt AS (SELECT m, l, sum(v) v FROM v GROUP BY 1, 2),
            ms AS (SELECT m, sum(v) tot FROM v GROUP BY 1),
            x AS (SELECT v.*, t.tot, (mt.v - v.v) / nullif(ms.tot - t.tot, 0) AS mshare
                  FROM v JOIN t USING (sid) JOIN mt ON mt.m = v.m AND mt.l = v.l JOIN ms ON ms.m = v.m)
            SELECT ? AS round_id, a.m AS municipality_name, a.sno AS station_no, a.sid AS station_id,
                   a.l AS empty_list, a.v AS empty_votes, round(a.mshare * a.tot, 1) AS empty_expected,
                   n.l AS neighbour_list, n.v AS neighbour_votes, round(n.mshare * n.tot, 1) AS neighbour_expected,
                   a.tot AS station_total
            FROM x a JOIN x n ON n.sid = a.sid AND abs(n.l - a.l) = 1
            WHERE a.mshare * a.tot >= 6 AND a.v <= 0.2 * a.mshare * a.tot
              AND n.v - n.mshare * n.tot >= 0.6 * a.mshare * a.tot
              AND n.v <= 3 * (a.mshare * a.tot + n.mshare * n.tot)
              AND n.mshare * n.tot < 0.5 * a.mshare * a.tot""", [rnd, rnd]).fetch_arrow_table().to_pylist()
    return rows


def _compare_with_previous(con, p: str, pairs: list[dict]) -> None:
    """Add `previous_*` columns: did the same station (linked through derived/station_links)
    give the neighbour list's party an unusually high share in the previous election too?
    If so the pattern is probably how that place votes, not a misplaced row."""
    from ._list_families import FAMILIES, PREVIOUS
    links = f"{DATA_ROOT}/parsed/derived/station_links.parquet"
    for row in pairs:
        row.update(previous_round=None, previous_station_id=None, previous_share=None,
                   previous_municipal_share=None, seen_before=None)
        prev = PREVIOUS.get(row["round_id"])
        family = FAMILIES.get(row["round_id"], {}).get(row["neighbour_list"])
        if not prev or not family:
            continue
        lists = [k for k, f in FAMILIES[prev].items() if f == family]
        if not lists:
            continue
        link = con.execute(f"""SELECT CASE WHEN round_a = ? THEN station_id_a ELSE station_id_b END
                               FROM read_parquet('{links}')
                               WHERE ((round_a = ? AND station_id_b = ?) OR (round_b = ? AND station_id_a = ?))
                                 AND rule IN ('number+name', 'renumbered', 'renamed')""",
                           [prev, prev, row["station_id"], prev, row["station_id"]]).fetchone()
        if not link:
            continue
        share = con.execute(f"""
            WITH r AS (SELECT s.municipality_name m, s.station_id sid, r.count_number l, coalesce(r.votes, 0) v
                       FROM read_parquet('{p}/stations.parquet') s
                       JOIN read_parquet('{p}/station_results.parquet') r USING (round_id, station_id)
                       WHERE s.round_id = ?),
                 me AS (SELECT m FROM r WHERE sid = ? LIMIT 1)
            SELECT sum(v) FILTER (WHERE sid = ? AND list_contains(?, l)) / nullif(sum(v) FILTER (WHERE sid = ?), 0),
                   sum(v) FILTER (WHERE sid <> ? AND list_contains(?, l)) / nullif(sum(v) FILTER (WHERE sid <> ?), 0)
            FROM r WHERE m = (SELECT m FROM me)""",
            [prev, link[0], link[0], lists, link[0], link[0], lists, link[0]]).fetchone()
        if share[0] is None:
            continue
        now_share = float(row["neighbour_votes"]) / float(row["station_total"])
        share = (float(share[0]), float(share[1] or 0))
        row.update(previous_round=prev, previous_station_id=link[0], previous_share=round(share[0], 4),
                   previous_municipal_share=round(share[1] or 0, 4),
                   seen_before=bool(share[0] >= max(2 * (share[1] or 0), 0.5 * now_share)))
