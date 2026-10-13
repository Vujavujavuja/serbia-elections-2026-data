"""Weekly voter register changes per municipality, pivoted by the kinds that move people.

Combines our own snapshots of the ministry's change table with the unofficial third-party
history (thirdparty_nemdub_register). Where both cover the same week, ours is kept. The
`origin` column says which source each week came from.

Columns are the ministry's own change types, renamed:
  entries_residence     "Упис по основу пријаве пребивалишта"
  deletions_residence   "Брисање по основу одјаве пребивалишта"
  address_changes       "Промена адресе пребивалишта"
  deaths                "Брисање по основу смрти лица"
  turned_18             "Упис по основу стицања пунолетства"
  ex_officio_deletions  "Брисање по службеној дужности"
  all_changes           every change type summed
"""
from __future__ import annotations

import duckdb

from ..store import DATA_ROOT
from ..tables import write_table

NAME = "register_flows"
DESCRIPTION = "Weekly register entries/deletions by residence per municipality (own + third-party history)"

TYPES = {
    "entries_residence": "Упис по основу пријаве пребивалишта",
    "deletions_residence": "Брисање по основу одјаве пребивалишта",
    "address_changes": "Промена адресе пребивалишта",
    "deaths": "Брисање по основу смрти лица",
    "turned_18": "Упис по основу стицања пунолетства",
    "ex_officio_deletions": "Брисање по службеној дужности",
}


def build() -> dict[str, int]:
    con = duckdb.connect()
    parsed = f"{DATA_ROOT}/parsed"
    pivots = ", ".join(f"coalesce(sum(n) FILTER (WHERE change_type = '{label}'), 0) AS {col}"
                       for col, label in TYPES.items())
    rows = con.execute(f"""
        WITH own AS (
            SELECT municipality, change_type, changes AS n, origin,
                   strptime(period_from, '%d.%m.%Y')::DATE AS week_start,
                   strptime(period_to, '%d.%m.%Y')::DATE AS week_end
            FROM read_parquet('{parsed}/voter_register/changes.parquet')
            QUALIFY fetched_at = max(fetched_at) OVER (PARTITION BY period_to)),
        third AS (
            SELECT "ОПШТИНА_ГРАД", "ВРСТА_ПРОМЕНЕ", TRY_CAST("БРОЈ_ПРОМЕНА" AS BIGINT), origin,
                   strptime("ПЕРИОД_ОД", '%d.%m.%Y')::DATE, strptime("ПЕРИОД_ДО", '%d.%m.%Y')::DATE
            FROM read_parquet('{parsed}/thirdparty_nemdub_register/changes.parquet')
            WHERE strptime("ПЕРИОД_ДО", '%d.%m.%Y')::DATE NOT IN (SELECT week_end FROM own)),
        unioned AS (SELECT * FROM own UNION ALL SELECT * FROM third)
        SELECT municipality AS register_name, strftime(week_start, '%Y-%m-%d') AS week_start,
               strftime(week_end, '%Y-%m-%d') AS week_end, any_value(origin) AS origin,
               {pivots}, sum(n) AS all_changes
        FROM unioned GROUP BY ALL ORDER BY 1, 2""").fetch_arrow_table().to_pylist()
    for row in rows:
        row["net_residence"] = row["entries_residence"] - row["deletions_residence"]
    write_table("derived", NAME, rows)
    return {NAME: len(rows)}
