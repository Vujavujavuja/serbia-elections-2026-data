"""Republic Geodetic Authority (RGZ): register of spatial units, anonymous export.

Boundaries of districts, municipalities and settlements as CSV with WKT geometry
(coordinates appear to be UTM zone 34N). The codes match the statistics office's.
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile

from ..http import Fetcher
from ..store import RawStore
from ..tables import write_table
from ._common import provenance

NAME = "rgz_boundaries"
DESCRIPTION = "Boundaries of districts, municipalities, settlements (download.geosrbija.rs open export)"

URL = "https://download.geosrbija.rs/download-api/opendata-proxy/export"
LAYERS = ("okrug_rpj", "opstina_rpj", "naselje_rpj")


def fetch(store: RawStore, layers: str = ",".join(LAYERS)) -> None:
    fetcher = Fetcher(store, NAME, min_interval=1.0, timeout=600)
    for layer in layers.split(","):
        fetcher.fetch(URL, query={"category": "rpj", "layer": layer, "geometry": "true",
                                  "fileName": layer, "format": "csv"}, ext=".zip", tags={"layer": layer})
    fetcher.close()


def parse(store: RawStore) -> dict[str, int]:
    csv.field_size_limit(sys.maxsize)
    out = {}
    for layer, r in store.latest(NAME, key=lambda r: r["tags"].get("layer")).items():
        rows = []
        with zipfile.ZipFile(io.BytesIO(store.read(r))) as archive:
            for member in archive.namelist():
                if not member.lower().endswith(".csv"):
                    continue
                text = archive.read(member).decode("utf-8-sig", "replace")
                for row in csv.DictReader(io.StringIO(text, newline="")):
                    rows.append({**row, "zip_member": member, **provenance(r)})
        write_table(NAME, layer, rows)
        out[layer] = len(rows)
    return out
