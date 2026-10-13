"""Statistical Office of the Republic of Serbia (RZS): open-data service.

Each dataset is served whole as CSV at
https://opendata.stat.gov.rs/data/WcfJsonRestService.Service1.svc/dataset/<ID>/1/csv
The catalogue of ids is at https://opendata.stat.gov.rs/odata/ . Add ids to DATASETS to collect more.
"""
from __future__ import annotations

from ..http import Fetcher
from ..store import RawStore
from ..tables import write_table
from ._common import provenance, read_delimited

NAME = "rzs"
DESCRIPTION = "Statistics office datasets: code lists, census 2022, population, deaths, migration, past results by municipality"

URL = "https://opendata.stat.gov.rs/data/WcfJsonRestService.Service1.svc/dataset/{id}/1/csv"
DATASETS = {
    "SIFOPS": "codes_municipalities",
    "SIFNAS": "codes_settlements",
    "3104020102IND01": "census2022_ethnicity",
    "18030302IND01": "population_estimates_age_sex",
    "18010403IND01": "population_estimates_1jan",
    "180304IND04": "deaths",
    "180402IND01": "internal_migration",
    "18060401IND01": "daily_migration_2022",
    "07021101IND01": "parliamentary_2023_by_municipality",
}


def fetch(store: RawStore, only: str = "") -> None:
    fetcher = Fetcher(store, NAME, min_interval=1.0, timeout=300)
    for dataset in (only.split(",") if only else DATASETS):
        fetcher.fetch(URL.format(id=dataset), ext=".csv", tags={"dataset": dataset})
    fetcher.close()


def parse(store: RawStore) -> dict[str, int]:
    out = {}
    latest = store.latest(NAME, key=lambda r: r["tags"].get("dataset"))
    for dataset, r in latest.items():
        rows = [{**row, "dataset_id": dataset, **provenance(r)} for row in read_delimited(store.read(r))]
        table = DATASETS.get(dataset, f"dataset_{dataset.lower()}")
        write_table(NAME, table, rows)
        out[table] = len(rows)
    return out
