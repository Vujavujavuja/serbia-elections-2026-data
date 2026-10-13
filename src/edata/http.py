"""HTTP client that writes everything it receives into the raw store."""
from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from .store import RawStore

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class Fetcher:
    def __init__(self, store: RawStore, source: str, *, min_interval: float = 0.25,
                 headers: dict[str, str] | None = None, timeout: float = 60.0):
        self.store = store
        self.source = source
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, **(headers or {})},
            timeout=timeout, follow_redirects=True,
        )

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def fetch(self, url: str, *, method: str = "GET", data: dict[str, Any] | None = None,
              query: dict[str, Any] | None = None, ext: str = "", tags: dict[str, Any] | None = None,
              retries: int = 4, save_errors: bool = True,
              origin: str = "direct") -> tuple[dict[str, Any] | None, bytes]:
        last_exc: Exception | None = None
        for attempt in range(retries):
            self._throttle()
            try:
                resp = self.client.request(method, url, data=data, params=query)
            except httpx.HTTPError as exc:
                last_exc = exc
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 500 or resp.status_code == 429:
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400 and not save_errors:
                return None, resp.content
            record = self.store.save(
                self.source, str(resp.request.url), resp.content, method=method,
                params={**(data or {}), **(query or {})}, status=resp.status_code,
                headers=dict(resp.headers), ext=ext, tags=tags, origin=origin,
            )
            return record, resp.content
        raise RuntimeError(f"{method} {url} failed after {retries} attempts: {last_exc}")

    def close(self) -> None:
        self.client.close()
