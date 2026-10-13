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

Research phase: mapping which public sources exist, in what format, and how
each is accessed. No modules are built yet.

## Data in this repository

Code and source documentation are committed here. Raw fetched data is not
committed by default (see `.gitignore`).
