"""Election-night loop: sweep RIK, rebuild tables, run the checks, write a status file.

    uv run edata live                      # 25 Oct 2026 parliamentary (RIK round 680072)
    uv run edata live --interval 600 --full-every 6

Writes findings/live/<round>/status.md (overwritten each pass) and findings/live/alerts.csv
(findings/live/<round>/alerts.csv, appended, one row per new alert with the time it was first seen). Stop with Ctrl+C;
nothing is lost, every response is already in the raw store.
"""
from __future__ import annotations

import csv
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .derived import discover as discover_derived
from .sources import rik_results
from .store import DATA_ROOT, RawStore
from .tables import build_db

LIVE = Path.cwd() / "findings" / "live"
CHECKS = ("result_checks", "row_shift", "result_versions")


def _alerts(round_id: str) -> list[dict]:
    con = duckdb.connect()
    p = f"{DATA_ROOT}/parsed/derived"
    out = []
    for rule, mun, no, detail in con.execute(f"""
            SELECT rule, municipality_name, station_no, detail FROM read_parquet('{p}/result_checks.parquet')
            WHERE round_id = ?""", [round_id]).fetchall():
        out.append({"check": "arithmetic:" + rule, "municipality": mun, "station_no": no, "detail": detail})
    for mun, no, arr, dev, after in con.execute(f"""
            SELECT municipality_name, station_no, best_arrangement, deviance_per_vote, deviance_after_undo
            FROM read_parquet('{p}/row_shift.parquet')
            WHERE round_id = ? AND deviance_per_vote >= 0.5 AND deviance_after_undo <= 0.2""", [round_id]).fetchall():
        out.append({"check": "row_shift_candidate", "municipality": mun, "station_no": no,
                    "detail": f"{arr}; deviance {dev} -> {after} after undo"})
    for mun, no, el, ev, ee, nl, nv in con.execute(f"""
            SELECT municipality_name, station_no, empty_list, empty_votes, empty_expected, neighbour_list, neighbour_votes
            FROM read_parquet('{p}/row_shift_pairs.parquet') WHERE round_id = ?""", [round_id]).fetchall():
        out.append({"check": "row_shift_neighbour", "municipality": mun, "station_no": no,
                    "detail": f"list {el} has {ev} (expected ~{ee}); list {nl} has {nv}"})
    path = Path(f"{p}/result_versions.parquet")
    if path.exists():
        for mun, no, version, seen, votes in con.execute(f"""
                SELECT municipality_name, station_no, version, seen, votes FROM read_parquet('{path}')
                WHERE round_id = ? AND version > 1""", [round_id]).fetchall():
            out.append({"check": "changed_after_publication", "municipality": mun, "station_no": no,
                        "detail": f"version {version} first seen {seen}: votes {votes}"})
    return out


def run(round_id: str = "680072", interval: int = 600, full_every: int = 6, cycles: int = 0) -> None:
    store = RawStore()
    live = LIVE / round_id
    live.mkdir(parents=True, exist_ok=True)
    alerts_path = live / "alerts.csv"
    seen = set()
    if alerts_path.exists():
        seen = {(r["check"], r["municipality"], r["station_no"], r["detail"]) for r in csv.DictReader(alerts_path.open())}
    checks = {k: v for k, v in discover_derived().items() if k in CHECKS}
    cycle, any_results = 0, False
    while True:
        cycle += 1
        started = time.monotonic()
        full = any_results and cycle % full_every == 0
        info = rik_results.sweep(store, round_id, full=full)
        rik_results.parse(store)
        for module in checks.values():
            module.build()
        build_db()
        any_results = any_results or (info["processed_stations"] not in (None, "0", 0))
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        new = []
        for a in _alerts(round_id):
            key = (a["check"], a["municipality"], a["station_no"], a["detail"])
            if key not in seen:
                seen.add(key); new.append({"first_seen": now, **a})
        if new:
            write_header = not alerts_path.exists()
            with alerts_path.open("a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["first_seen", "check", "municipality", "station_no", "detail"])
                if write_header:
                    w.writeheader()
                w.writerows(new)
        took = time.monotonic() - started
        (live / "status.md").write_text(
            f"# Election night status\n\nLast pass: {now} (cycle {cycle}, {'full' if full else 'changed only'}, {took:.0f}s)\n\n"
            f"- RIK processed stations: {info['processed_stations']} of {info['number_of_stations']}\n"
            f"- RIK results time: {info['results_datetime']}\n"
            f"- Municipalities changed this pass: {info['municipalities_changed']}\n"
            f"- Stations fetched this pass: {info['stations_fetched']}\n"
            f"- Alerts in total: {len(seen)} (new this pass: {len(new)})\n")
        print(f"[{now}] cycle {cycle}: processed {info['processed_stations']}/{info['number_of_stations']}, "
              f"{info['municipalities_changed']} municipalities changed, {info['stations_fetched']} stations fetched, "
              f"{len(new)} new alerts, {took:.0f}s", flush=True)
        if cycles and cycle >= cycles:
            return
        time.sleep(max(30, interval - took))
