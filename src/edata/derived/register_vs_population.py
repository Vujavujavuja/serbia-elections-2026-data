"""Registered voters per municipality next to the statistics office's population estimate.

Voters: latest snapshot of the ministry's open table (voter_register.counts).
Population: RZS estimate on 1 January of the latest available year, by single year of age.

The two sources name municipalities differently and neither table carries a shared code, so
names are matched here; `match_rule` records how. Municipalities in Kosovo have no RZS
estimate and are kept with empty population columns.

The dates differ (population: 1 Jan of `population_year`; voters: `voters_as_of`). Two adult
counts are given: aged 18+ on the estimate date, and aged 16+ on the estimate date (everyone
old enough to turn 18 within two years, with no deaths or migration applied).
"""
from __future__ import annotations

import re

import duckdb

from ..store import DATA_ROOT
from ..tables import write_table

NAME = "register_vs_population"
DESCRIPTION = "Registered voters vs RZS adult population estimate, per municipality"

CITY_PREFIXES = ("БЕОГРАД-", "НИШ-", "ВРАЊЕ-", "ПОЖАРЕВАЦ-", "УЖИЦЕ-")
ALIASES = {  # register name -> RZS municipality code, where names alone are ambiguous
    "БЕОГРАД-ПАЛИЛУЛА": "70203", "НИШ-ПАЛИЛУЛА": "71323", "НОВИ САД - ГРАД": "89010",
}


def norm(name: str) -> str:
    return re.sub(r"[^А-ЯЁЂЈЉЊЋЏ]", "", name.upper())


def build() -> dict[str, int]:
    con = duckdb.connect()
    parsed = f"{DATA_ROOT}/parsed"
    pop = f"read_parquet('{parsed}/rzs/population_estimates_1jan.parquet')"
    year = con.execute(f"SELECT max(god) FROM {pop}").fetchone()[0]
    population = {}
    for code, name, total, p18, p16 in con.execute(f"""
        SELECT IDTer, any_value(nTer),
               sum(CASE WHEN IDStarost = '0' THEN v END),
               sum(CASE WHEN IDStarost <> '0' AND age >= 18 THEN v END),
               sum(CASE WHEN IDStarost <> '0' AND age >= 16 THEN v END)
        FROM (SELECT IDTer, nTer, IDStarost, TRY_CAST(vrednost AS BIGINT) AS v,
                     TRY_CAST(regexp_replace(IDStarost, '[^0-9]', '', 'g') AS INTEGER) AS age
              FROM {pop} WHERE god = ? AND IDPol = '0')
        GROUP BY IDTer""", [year]).fetchall():
        population[code] = (name, total, p18, p16)
    by_name = {norm(v[0]): code for code, v in population.items()
               if code.isdigit() and not code.startswith(("79", "89"))}

    reg = f"read_parquet('{parsed}/voter_register/counts.parquet')"
    rows = []
    for name, voters, as_of, fetched_at, sha in con.execute(f"""
        SELECT municipality, voters, as_of, fetched_at, raw_sha256 FROM {reg}
        WHERE fetched_at = (SELECT max(fetched_at) FROM {reg}) ORDER BY municipality""").fetchall():
        if name in ALIASES:
            code, rule = ALIASES[name], "alias"
        else:
            stripped = name.removesuffix(" - ГРАД")
            for prefix in CITY_PREFIXES:
                stripped = stripped.removeprefix(prefix)
            code = by_name.get(norm(stripped))
            rule = "name" if code else "no_population_data"
        _, total, p18, p16 = population.get(code, (None, None, None, None))
        rows.append({
            "register_name": name, "rzs_code": code, "rzs_name": population[code][0] if code else None,
            "match_rule": rule, "voters": voters, "voters_as_of": as_of,
            "population_year": year, "population_total": total, "population_18plus": p18,
            "population_16plus": p16,
            "voters_minus_18plus": voters - p18 if p18 else None,
            "voters_per_100_18plus": round(100 * voters / p18, 2) if p18 else None,
            "voters_per_100_16plus": round(100 * voters / p16, 2) if p16 else None,
            "register_fetched_at": fetched_at, "register_raw_sha256": sha})
    write_table("derived", NAME, rows)
    return {NAME: len(rows)}
