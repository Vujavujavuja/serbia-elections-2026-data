"""Stations whose published numbers changed after they were first published.

Every sweep stores a new copy of each station's response. This compares the numbers in
successive copies (turnout, ballots, votes per list), ignoring timestamps, and lists every
station where they changed, with the old and new values and when each was first seen.
"""
from __future__ import annotations

import duckdb

from ..store import DATA_ROOT
from ..tables import write_table

NAME = "result_versions"
DESCRIPTION = "Stations whose published results changed between sweeps"


def build() -> dict[str, int]:
    con = duckdb.connect()
    p = f"{DATA_ROOT}/parsed/rik_results"
    rows = con.execute(f"""
        WITH v AS (
            SELECT m.round_id, m.station_id, m.raw_sha256, m.first_fetched_at,
                   m.total_voters, m.turnout_value_1 AS voted, m.ballots_value_0 AS valid, m.ballots_value_1 AS invalid,
                   (SELECT string_agg(coalesce(r.votes, -1)::VARCHAR, ',' ORDER BY r.count_number)
                    FROM read_parquet('{p}/station_results.parquet') r
                    WHERE r.round_id = m.round_id AND r.station_id = m.station_id AND r.raw_sha256 = m.raw_sha256) AS votes
            FROM read_parquet('{p}/station_summary.parquet') m),
        n AS (  -- one row per distinct set of numbers, first time it was seen
            SELECT round_id, station_id, total_voters, voted, valid, invalid, votes, min(first_fetched_at) AS seen
            FROM v WHERE coalesce(voted, 0) > 0 GROUP BY ALL),
        o AS (SELECT *, row_number() OVER (PARTITION BY round_id, station_id ORDER BY seen) AS version,
                     count(*) OVER (PARTITION BY round_id, station_id) AS versions FROM n)
        SELECT o.*, s.municipality_name, s.station_no, s.station_name
        FROM o JOIN read_parquet('{p}/stations.parquet') s USING (round_id, station_id)
        WHERE versions > 1 ORDER BY round_id, municipality_name, station_no, version""").fetch_arrow_table().to_pylist()
    write_table("derived", NAME, rows)
    return {NAME: len(rows)}
