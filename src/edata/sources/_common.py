"""Helpers shared by collectors (not a collector itself: the leading underscore hides it)."""
from __future__ import annotations

import csv
import io
import json

from ..http import Fetcher
from ..store import RawStore


def provenance(record: dict) -> dict:
    return {"source_url": record["url"], "fetched_at": record["fetched_at"],
            "raw_sha256": record["sha256"], "origin": record["origin"]}


def read_delimited(content: bytes, delimiter: str = ",") -> list[dict]:
    text = content.decode("utf-8-sig", "replace")
    return list(csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter))


def fetch_github_files(store: RawStore, source: str, repo: str, wanted) -> None:
    """Copy files from a public GitHub repository, pinned to the commit they came from."""
    fetcher = Fetcher(store, source, min_interval=0.1)
    api = f"https://api.github.com/repos/{repo}"
    commit = json.loads(fetcher.fetch(f"{api}/commits/HEAD", ext=".json", tags={"kind": "commit"})[1])
    sha, date = commit["sha"], commit["commit"]["committer"]["date"]
    tree = json.loads(fetcher.fetch(f"{api}/git/trees/{sha}", query={"recursive": 1}, ext=".json",
                                    tags={"kind": "tree", "commit": sha})[1])
    have = {(r["tags"].get("path"), r["tags"].get("blob")) for r in store.manifest(source)}
    for item in tree["tree"]:
        if item["type"] != "blob" or not wanted(item["path"]) or (item["path"], item["sha"]) in have:
            continue
        ext = "." + item["path"].rsplit(".", 1)[-1] if "." in item["path"] else ""
        fetcher.fetch(f"https://raw.githubusercontent.com/{repo}/{sha}/{item['path']}", ext=ext,
                      tags={"kind": "file", "path": item["path"], "blob": item["sha"],
                            "commit": sha, "commit_date": date},
                      origin=f"github:{repo}")
    fetcher.close()


def latest_files(store: RawStore, source: str) -> dict[str, dict]:
    return {r["tags"]["path"]: r for r in store.manifest(source)
            if r["tags"].get("kind") == "file" and r["status"] == 200}
