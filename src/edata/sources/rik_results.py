"""Republic Electoral Commission (RIK): results per polling station.

The public results page (https://www.rik.parlament.gov.rs/542645/rezultati/) loads its
data from JSON endpoints. This collector walks the same hierarchy the page does
(election -> region -> municipality -> polling station) and stores every response.

The per-station response also lists the scanned polling-board records (PDF links with
upload times); those links are parsed into their own table, the PDFs are not downloaded here.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from html import unescape

from lxml import html as lxml_html

from ..http import Fetcher
from ..store import RawStore
from ..tables import write_table

NAME = "rik_results"
DESCRIPTION = "RIK results per polling station (JSON behind rik.parlament.gov.rs/542645/rezultati/)"

BASE = "https://www.rik.parlament.gov.rs"
ELECTION_TYPES = {"2": "Парламентарни", "3": "Локални", "7": "Покрајински"}


def _int(value) -> int | None:
    if value is None:
        return None
    digits = re.sub(r"[.\s]", "", str(value))
    return int(digits) if re.fullmatch(r"-?\d+", digits) else None


def _json(content: bytes):
    try:
        return json.loads(content)
    except ValueError:
        return None


def _options(fragment: bytes) -> list[tuple[str, str | None, str]]:
    """(value, data-id, text) for each <option> in an HTML fragment."""
    text = fragment.decode("utf-8", "replace")
    out = []
    for attrs, label in re.findall(r"<option([^>]*)>(.*?)</option>", text, flags=re.S):
        value = re.search(r'value="([^"]*)"', attrs)
        data_id = re.search(r'data-id="([^"]*)"', attrs)
        if value and value.group(1) != "0":
            out.append((value.group(1), data_id.group(1) if data_id else None, unescape(label)))
    return out


def fetch(store: RawStore, rounds: str = "all", results: str = "yes", refresh: str = "no",
          workers: str = "4") -> None:
    """rounds: comma-separated RIK election ids, or "all".
    results: "no" collects only the list of regions/municipalities/stations.
    refresh: "yes" re-fetches station results already in the store (use while counting is live).
    """
    fetcher = Fetcher(store, NAME, min_interval=0.12, headers={
        "X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/542645/rezultati/"})
    wanted = None if rounds == "all" else set(rounds.split(","))
    done = set()
    if refresh != "yes":
        done = {(r["tags"]["round"], r["tags"]["station"]) for r in store.manifest(NAME)
                if r["tags"].get("kind") == "results" and r["status"] == 200}

    def post(path: str, data: dict, **tags):
        return fetcher.fetch(f"{BASE}{path}", method="POST", data=data, ext=".json", tags=tags)[1]

    for etype in ELECTION_TYPES:
        listing = _json(post("/get-elections/", {"election_type": etype}, kind="elections", type=etype))
        for round_id in (listing or {}).get("rounds", {}):
            if wanted is not None and round_id not in wanted:
                continue
            base = {"election_type": etype, "election_round": round_id}
            tag = {"type": etype, "round": round_id}
            regions = _json(post("/get-regions/", base, kind="regions", **tag)) or {}
            jobs = []
            for region in regions.get("regions", {}):
                munis = fetcher.fetch(
                    f"{BASE}/get-municipalities/", method="POST", ext=".html",
                    data={**base, "election_region": region},
                    tags={"kind": "municipalities", "region": region, **tag})[1]
                for muni, _, _ in _options(munis):
                    stations = _json(post(
                        "/get-election-stations/",
                        {**base, "election_region": region, "election_municipality": muni},
                        kind="stations", region=region, municipality=muni, **tag)) or {}
                    for station in stations.get("election_stations", {}):
                        if (round_id, station) not in done:
                            jobs.append((region, muni, station))
            print(f"{NAME}: round {round_id}: {len(jobs)} stations to fetch", flush=True)
            if results != "yes":
                continue
            post("/get_results/", {"should_update_pies": 1, "type": etype, "election_round": round_id,
                                   "region": 0, "municipality": 0, "election_station": 0},
                 kind="results_total", **tag)

            def one(job, etype=etype, round_id=round_id, tag=tag):
                region, muni, station = job
                post("/get_results/", {"should_update_pies": 1, "type": etype,
                                       "election_round": round_id, "region": region,
                                       "municipality": muni, "election_station": station},
                     kind="results", region=region, municipality=muni, station=station, **tag)

            with ThreadPoolExecutor(max_workers=int(workers)) as pool:
                for i, _ in enumerate(pool.map(one, jobs), 1):
                    if i % 500 == 0:
                        print(f"{NAME}: round {round_id}: {i}/{len(jobs)}", flush=True)
    fetcher.close()


def _documents(fragment: str) -> list[dict]:
    if not fragment.strip():
        return []
    rows, doc_type = [], None
    for div in lxml_html.fragment_fromstring(fragment, create_parent="div").iterchildren("div"):
        link = div.find(".//a")
        if link is None:
            doc_type = " ".join(div.text_content().split())
            continue
        spans = div.xpath("./span")
        rows.append({
            "doc_type": doc_type,
            "file_name": " ".join(link.text_content().split()),
            "href": link.get("href"),
            "uploaded_at": " ".join(spans[-1].text_content().split()) if spans else None,
        })
    return rows


def parse(store: RawStore) -> dict[str, int]:
    rounds, regions, munis, stations = {}, {}, {}, []
    versions: dict[tuple, dict] = {}
    for r in store.manifest(NAME):
        if r["status"] != 200:
            continue
        t, kind = r["tags"], r["tags"].get("kind")
        if kind == "elections":
            for rid, name in (_json(store.read(r)) or {}).get("rounds", {}).items():
                rounds[rid] = {"election_type": t["type"], "election_type_name": ELECTION_TYPES[t["type"]],
                               "round_id": rid, "round_name": name}
        elif kind == "regions":
            d = _json(store.read(r)) or {}
            for reg, name in d.get("regions", {}).items():
                regions[(t["round"], reg)] = (name, (d.get("data_id") or {}).get(reg))
        elif kind == "municipalities":
            for muni, code, name in _options(store.read(r)):
                munis[(t["round"], t["region"], muni)] = (name.strip(), code)
        elif kind == "stations":
            d = _json(store.read(r)) or {}
            for sid, label in d.get("election_stations", {}).items():
                stations.append((t["round"], t["region"], t["municipality"], sid, label, r))
        elif kind == "results":
            key = (t["round"], t["station"], r["sha256"])
            if key in versions:
                versions[key]["last_fetched_at"] = r["fetched_at"]
            else:
                versions[key] = {"record": r, "first_fetched_at": r["fetched_at"],
                                 "last_fetched_at": r["fetched_at"]}

    station_rows = {}
    for rid, reg, muni, sid, label, r in stations:
        number, _, name = label.partition(" - ")
        station_rows[(rid, sid)] = {
            "round_id": rid, "region_id": reg, "region_name": regions.get((rid, reg), (None, None))[0],
            "region_code": regions.get((rid, reg), (None, None))[1],
            "municipality_id": muni, "municipality_name": munis.get((rid, reg, muni), (None, None))[0],
            # RIK's data-id on the municipality: the statistics office's municipality code
            "municipality_code": munis.get((rid, reg, muni), (None, None))[1],
            "station_id": sid, "station_label": label, "station_no": number.strip(),
            "station_name": name.strip(), "listed_at": r["fetched_at"], "raw_sha256": r["sha256"],
        }

    summary, results, documents = [], [], []
    for (rid, sid, sha), v in versions.items():
        d = _json(store.read(v["record"]))
        if d is None:
            continue
        ident = {"round_id": rid, "station_id": sid, "raw_sha256": sha, "source_url": v["record"]["url"],
                 "first_fetched_at": v["first_fetched_at"], "last_fetched_at": v["last_fetched_at"]}
        stat = d.get("stat_sum_numbers") or {}
        turnout = ((d.get("processed_config") or {}).get("data") or {})
        ballots = ((d.get("sum_config") or {}).get("data") or {})

        def pie(block, i):
            values = (block.get("datasets") or [{}])[0].get("data") or []
            labels = block.get("labels") or []
            return (values[i] if i < len(values) else None, labels[i] if i < len(labels) else None)

        summary.append({
            **ident, "election_title": stat.get("election_title"), "results_datetime": stat.get("datetime"),
            "total_voters_raw": stat.get("total_voters"), "total_voters": _int(stat.get("total_voters")),
            "available_raw": stat.get("available"), "available": _int(stat.get("available")),
            "number_of_stations": _int(stat.get("number_of_stations")),
            "processed_stations": _int(stat.get("processed_stations")),
            "turnout_value_0": pie(turnout, 0)[0], "turnout_label_0": pie(turnout, 0)[1],
            "turnout_value_1": pie(turnout, 1)[0], "turnout_label_1": pie(turnout, 1)[1],
            "ballots_value_0": pie(ballots, 0)[0], "ballots_label_0": pie(ballots, 0)[1],
            "ballots_value_1": pie(ballots, 1)[0], "ballots_label_1": pie(ballots, 1)[1],
        })
        for row in d.get("table_data") or []:
            results.append({**ident, "count_number": row.get("count_number"),
                            "list_name": row.get("list_name"), "won_number_raw": row.get("won_number"),
                            "votes": _int(row.get("won_number")), "won_percent": row.get("won_percent")})
        for doc in _documents(d.get("minute_from_election_station") or ""):
            documents.append({**ident, **doc})

    out = {
        "rounds": list(rounds.values()),
        "stations": list(station_rows.values()),
        "station_summary": summary,
        "station_results": results,
        "station_documents": documents,
    }
    for table, rows in out.items():
        write_table(NAME, table, rows)
    return {table: len(rows) for table, rows in out.items()}


def _fingerprint(content: bytes) -> tuple | None:
    """What counts as a change in an aggregate response: numbers only, not its timestamp."""
    d = _json(content)
    if not d:
        return None
    s = d.get("stat_sum_numbers") or {}
    votes = tuple((row.get("count_number"), row.get("won_number")) for row in d.get("table_data") or [])
    return (s.get("processed_stations"), s.get("total_voters"), s.get("available"), votes)


def sweep(store: RawStore, round_id: str, full: bool = False, workers: int = 2) -> dict:
    """One election-night pass, light on both ends.

    1. Fetch the national total and every municipality's aggregate (about 200 requests).
    2. Re-fetch the stations of municipalities whose aggregate changed since the last pass,
       or of every municipality when `full` is set (to catch changes that cancel out).
    Every response is stored as usual, so each pass adds a timestamped version.
    """
    fetcher = Fetcher(store, NAME, min_interval=0.2, headers={
        "X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/542645/rezultati/"})
    etype = None
    previous, stations = {}, {}
    for r in store.manifest(NAME):
        t = r["tags"]
        if t.get("round") != round_id or r["status"] != 200:
            continue
        etype = t.get("type", etype)
        if t.get("kind") == "results_municipality":
            previous[(t["region"], t["municipality"])] = r
        elif t.get("kind") == "stations":
            d = _json(store.read(r)) or {}
            stations[(t["region"], t["municipality"])] = list(d.get("election_stations", {}))
    if etype is None:
        raise RuntimeError(f"round {round_id}: run `edata fetch rik_results rounds={round_id} results=no` first")

    def post(data, **tags):
        return fetcher.fetch(f"{BASE}/get_results/", method="POST", ext=".json",
                             data={"should_update_pies": 1, "type": etype, "election_round": round_id, **data},
                             tags={"type": etype, "round": round_id, **tags})[1]

    total = _json(post({"region": 0, "municipality": 0, "election_station": 0}, kind="results_total")) or {}
    changed = []
    for (region, muni) in sorted(stations):
        content = post({"region": region, "municipality": muni, "election_station": 0},
                       kind="results_municipality", region=region, municipality=muni)
        before = previous.get((region, muni))
        if full or before is None or _fingerprint(store.read(before)) != _fingerprint(content):
            changed.append((region, muni))
    jobs = [(region, muni, sid) for region, muni in changed
            if full or (region, muni) in previous for sid in stations[(region, muni)]]

    def one(job):
        region, muni, sid = job
        post({"region": region, "municipality": muni, "election_station": sid},
             kind="results", region=region, municipality=muni, station=sid)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    fetcher.close()
    s = total.get("stat_sum_numbers") or {}
    return {"processed_stations": s.get("processed_stations"), "number_of_stations": s.get("number_of_stations"),
            "results_datetime": s.get("datetime"), "municipalities_changed": len(changed),
            "stations_fetched": len(jobs)}
