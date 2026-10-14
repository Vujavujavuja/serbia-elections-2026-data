"""Arithmetic checks on published per-station results (rik_results).

Each row is one station failing one rule. Rules use only the station's own published figures:

  votes_ne_valid        sum of list votes differs from valid ballots
  ballots_gt_voted      valid + invalid ballots exceed voters recorded as turned out
  voted_gt_registered   voters recorded as turned out exceed registered voters
  voted_eq_registered   turnout recorded as exactly the registered number while fewer ballots were counted
  voted_gt_ballots_10   voters recorded as turned out exceed ballots counted by 10 or more
  percent_mismatch      a published list percentage differs from votes / ballots in the box by more than
                        0.01 (RIK computes list percentages on all ballots in the box, valid and invalid)
  duplicate_vector      the full vector of list votes (at least 50 votes) is identical to another station's

Failing a rule is a fact about the published numbers, not a finding about why.
"""
from __future__ import annotations

import duckdb

from ..store import DATA_ROOT
from ..tables import write_table

NAME = "result_checks"
DESCRIPTION = "Stations whose published results break arithmetic rules"


def build() -> dict[str, int]:
    con = duckdb.connect()
    p = f"{DATA_ROOT}/parsed/rik_results"
    con.execute(f"""
        CREATE TEMP TABLE s AS
        SELECT st.round_id, st.station_id, st.region_name, st.municipality_name, st.station_no, st.station_name,
               m.total_voters AS registered, m.turnout_value_1 AS voted,
               m.ballots_value_0 AS valid, m.ballots_value_1 AS invalid, m.raw_sha256
        FROM read_parquet('{p}/stations.parquet') st
        JOIN read_parquet('{p}/station_summary.parquet') m USING (round_id, station_id)""")
    con.execute(f"""
        CREATE TEMP TABLE v AS
        SELECT round_id, station_id, sum(votes) AS votes,
               max(abs(won_percent - round(100.0 * votes / nullif(valid + invalid, 0), 2))) AS pct_err,
               string_agg(coalesce(votes, -1)::VARCHAR, ',' ORDER BY count_number) AS vector
        FROM read_parquet('{p}/station_results.parquet') r JOIN s USING (round_id, station_id)
        GROUP BY ALL""")
    rows = con.execute("""
        WITH x AS (SELECT * FROM s JOIN v USING (round_id, station_id)),
        dup AS (SELECT round_id, vector, count(*) AS n, string_agg(station_id, ',') AS ids
                FROM x WHERE votes >= 50 GROUP BY ALL HAVING count(*) > 1)
        SELECT x.*, rule, detail FROM x, LATERAL (
            SELECT 'votes_ne_valid' AS rule, 'list votes ' || x.votes || ' vs valid ' || x.valid AS detail WHERE x.votes <> x.valid
            UNION ALL SELECT 'ballots_gt_voted', (x.valid + x.invalid) || ' ballots vs ' || x.voted || ' voted' WHERE x.valid + x.invalid > x.voted
            UNION ALL SELECT 'voted_gt_registered', x.voted || ' voted vs ' || x.registered || ' registered' WHERE x.voted > x.registered
            UNION ALL SELECT 'voted_eq_registered', x.voted || ' voted = registered, ' || (x.valid + x.invalid) || ' ballots'
                WHERE x.voted = x.registered AND x.valid + x.invalid < x.voted
            UNION ALL SELECT 'voted_gt_ballots_10', x.voted || ' voted vs ' || (x.valid + x.invalid) || ' ballots'
                WHERE x.voted - (x.valid + x.invalid) >= 10 AND x.voted <> x.registered
            UNION ALL SELECT 'percent_mismatch', 'max error ' || round(x.pct_err, 2) WHERE x.pct_err > 0.01
            UNION ALL SELECT 'duplicate_vector', 'same votes as stations ' || d.ids
                FROM dup d WHERE d.round_id = x.round_id AND d.vector = x.vector)
        ORDER BY round_id, rule, municipality_name, station_no""").fetch_arrow_table().to_pylist()
    write_table("derived", NAME, rows)
    return {NAME: len(rows)}
