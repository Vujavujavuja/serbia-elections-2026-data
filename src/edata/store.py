"""Raw store: every fetched response is kept byte-for-byte and never overwritten.

Layout under the data root:
    raw/<source>/<sha[:2]>/<sha256><ext>   response bodies, addressed by content hash
    manifest/<source>.jsonl                one line per fetch (provenance)
    parsed/<source>/<table>.parquet        tables derived from raw, rebuildable at any time
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DATA_ROOT = Path(os.environ.get("EDATA_ROOT", Path.cwd() / "data"))


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class RawStore:
    def __init__(self, root: Path = DATA_ROOT):
        self.root = Path(root)
        self._lock = threading.Lock()

    def save(
        self,
        source: str,
        url: str,
        content: bytes,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        status: int | None = None,
        headers: dict[str, str] | None = None,
        ext: str = "",
        tags: dict[str, Any] | None = None,
        fetched_at: str | None = None,
        origin: str = "direct",
    ) -> dict[str, Any]:
        """Store one response and append its provenance record. Returns the record."""
        sha = hashlib.sha256(content).hexdigest()
        rel = Path("raw") / source / sha[:2] / f"{sha}{ext}"
        path = self.root / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(content)
            tmp.replace(path)
        record = {
            "source": source,
            "url": url,
            "method": method,
            "params": params or {},
            "fetched_at": fetched_at or utcnow(),
            "status": status,
            "sha256": sha,
            "size": len(content),
            "path": str(rel),
            "content_type": (headers or {}).get("content-type"),
            "last_modified": (headers or {}).get("last-modified"),
            "tags": tags or {},
            # "direct" = fetched from the publisher; anything else names the intermediary
            "origin": origin,
        }
        manifest = self.root / "manifest" / f"{source}.jsonl"
        with self._lock:
            manifest.parent.mkdir(parents=True, exist_ok=True)
            with manifest.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def manifest(self, source: str) -> Iterator[dict[str, Any]]:
        path = self.root / "manifest" / f"{source}.jsonl"
        if not path.exists():
            return
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)

    def read(self, record: dict[str, Any]) -> bytes:
        return (self.root / record["path"]).read_bytes()

    def latest(self, source: str, key=lambda r: r["url"]) -> dict[Any, dict[str, Any]]:
        """Most recent successful record per key (default: per URL)."""
        out: dict[Any, dict[str, Any]] = {}
        for r in self.manifest(source):
            if r["status"] is None or 200 <= r["status"] < 300:
                out[key(r)] = r
        return out
