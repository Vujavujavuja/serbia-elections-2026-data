"""Parsed tables (parquet) and the DuckDB database that exposes them."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .store import DATA_ROOT


def write_table(source: str, table: str, rows: list[dict[str, Any]], root: Path = DATA_ROOT) -> Path:
    """Write rows to parsed/<source>/<table>.parquet, replacing the previous parse."""
    path = root / "parsed" / source / f"{table}.parquet"
    if not rows:
        path.unlink(missing_ok=True)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: dict[str, None] = {}
    for row in rows:
        columns.update(dict.fromkeys(row))
    data = {c: [row.get(c) for row in rows] for c in columns}
    try:
        tbl = pa.table(data)
    except (pa.ArrowInvalid, pa.ArrowTypeError):
        # mixed types in a column: keep the values, as text
        tbl = pa.table({c: [None if v is None else str(v) for v in vals] for c, vals in data.items()})
    pq.write_table(tbl, path)
    return path


def build_db(root: Path = DATA_ROOT) -> Path:
    """(Re)create data/elections.duckdb: one view per parsed table, plus the manifest."""
    db_path = root / "elections.duckdb"
    con = duckdb.connect(str(db_path))
    for parquet in sorted((root / "parsed").glob("*/*.parquet")):
        view = f"{parquet.parent.name}__{parquet.stem}"
        con.execute(f'CREATE OR REPLACE VIEW "{view}" AS SELECT * FROM read_parquet(\'{parquet}\')')
    manifests = root / "manifest" / "*.jsonl"
    if list((root / "manifest").glob("*.jsonl")):
        con.execute(
            "CREATE OR REPLACE VIEW manifest AS SELECT * FROM read_json_auto("
            f"'{manifests}', format='newline_delimited', union_by_name=true, "
            "columns={'source':'VARCHAR','url':'VARCHAR','method':'VARCHAR','params':'JSON',"
            "'fetched_at':'VARCHAR','status':'INTEGER','sha256':'VARCHAR','size':'BIGINT',"
            "'path':'VARCHAR','content_type':'VARCHAR','last_modified':'VARCHAR','tags':'JSON',"
            "'origin':'VARCHAR'})"
        )
    con.close()
    return db_path
