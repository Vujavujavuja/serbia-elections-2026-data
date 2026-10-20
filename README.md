# Serbia 2026 Elections: Data Foundation

Data sources and data streams for examining the integrity of Serbia's early
parliamentary elections on 25 October 2026 — before, during and after the vote.

This repository collects and structures public data. It does not publish
conclusions.

## Principles

- **Modular** — each source or stream is its own module behind a common
  interface, so one can be added, removed or swapped without touching the rest.
- **Full fidelity** — data is kept exactly as the source provides it. Nothing
  is aggregated, dropped or filtered.
- **Provenance** — every record carries where it came from and when it was
  fetched.
- **Queryable** — data can be explored as soon as it lands.

## Status

Collectors are being built and run ahead of election day. No analysis is published here yet.

## How it works

A *collector* is one Python file in `src/edata/sources/`. It pulls from one publisher,
stores every response unmodified, and rebuilds queryable tables from what it stored.
Collectors do not depend on each other: add a file to add a source, delete it to remove one.

    uv sync
    uv run edata list                  # collectors and their options
    uv run edata run voter_register    # fetch, parse, refresh the database
    uv run edata fetch rik_results rounds=341140
    uv run edata parse rik_results

Everything lands under `data/` (not committed):

- `data/raw/<collector>/` response bodies, byte for byte, named by SHA-256
- `data/manifest/<collector>.jsonl` one line per fetch: URL, request parameters, UTC time,
  HTTP status, hash, and whether it came from the publisher or a third party
- `data/parsed/<collector>/<table>.parquet` tables rebuilt from raw
- `data/elections.duckdb` one view per table, plus `manifest`

Parsed rows carry `source_url`, `fetched_at` and `raw_sha256`, so any value can be traced
to the stored response it came from.

## Election night

    caffeinate -dimsu uv run edata live

Every 10 minutes it fetches the national total and each municipality's totals from RIK
(about 200 requests), re-fetches the stations of municipalities whose numbers changed, and
every sixth pass re-fetches all stations. After each pass it rebuilds the tables and runs the
checks: arithmetic rules, row shifts (votes written against the wrong list), and stations whose
published numbers changed after first publication. Output, local only:

- `findings/live/<round>/status.md` current state, overwritten each pass
- `findings/live/<round>/alerts.csv` every alert with the time it was first seen

`caffeinate` keeps the Mac awake. Stop with Ctrl+C; every response is already stored.

## Collectors

| Collector | Publisher | What |
|---|---|---|
| `rik_results` | Republic Electoral Commission | Results per polling station, links to scanned polling-board records |
| `rik_documents` | Republic Electoral Commission | Polling-station decisions, candidate lists, commission decisions |
| `rik_archive` | Republic Electoral Commission | Result files for 2012-2020 |
| `voter_register` | Ministry of Public Administration | Voters and register changes per municipality |
| `rzs` | Statistical Office | Code lists, census 2022, population, deaths, migration |
| `rgz_boundaries` | Republic Geodetic Authority | District, municipality, settlement boundaries |
| `thirdparty_nemdub_register` | unofficial | Weekly voter register history since Feb 2026 |
| `thirdparty_majstors_stations` | unofficial | Geocoded 2026 polling stations |

## Data in this repository

Code only. Fetched data is not committed (see `.gitignore`).
