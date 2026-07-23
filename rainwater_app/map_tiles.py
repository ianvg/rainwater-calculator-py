from __future__ import annotations

import email.utils
import hashlib
import itertools
import json
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .app_paths import user_cache_dir


DEFAULT_TILE_CACHE_SECONDS = 7 * 24 * 60 * 60
DEFAULT_TILE_USER_AGENT = os.environ.get(
    "RWH_OSM_USER_AGENT", "RWH-Calculator/0.1.2 (desktop application)"
)


def _cache_expiry(headers: requests.structures.CaseInsensitiveDict, now: float) -> float:
    cache_control = headers.get("Cache-Control", "")
    match = re.search(r"(?:^|,)\s*max-age\s*=\s*(\d+)", cache_control, flags=re.IGNORECASE)
    if match:
        return now + int(match.group(1))
    expires = headers.get("Expires")
    if expires:
        try:
            parsed = email.utils.parsedate_to_datetime(expires)
            return parsed.timestamp()
        except (TypeError, ValueError, OverflowError):
            pass
    return now + DEFAULT_TILE_CACHE_SECONDS


class HttpTileCache:
    """Small HTTP-aware on-disk cache for interactive raster map tiles."""

    def __init__(self, cache_dir: Path, *, user_agent: str = DEFAULT_TILE_USER_AGENT) -> None:
        self.cache_dir = Path(cache_dir)
        self.user_agent = user_agent
        self._thread_local = threading.local()
        self._url_locks: dict[str, threading.Lock] = {}
        self._url_locks_guard = threading.Lock()

    def _session(self) -> requests.Session:
        session = getattr(self._thread_local, "session", None)
        if session is None:
            retry = Retry(
                total=2,
                connect=2,
                read=1,
                backoff_factor=0.25,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                respect_retry_after_header=True,
            )
            adapter = HTTPAdapter(max_retries=retry, pool_connections=6, pool_maxsize=6)
            session = requests.Session()
            session.headers.update({"User-Agent": self.user_agent})
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._thread_local.session = session
        return session

    def _paths(self, url: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.tile", self.cache_dir / f"{digest}.json"

    def _url_lock(self, url: str) -> threading.Lock:
        with self._url_locks_guard:
            return self._url_locks.setdefault(url, threading.Lock())

    @staticmethod
    def _read_metadata(path: Path) -> dict[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, url: str) -> bytes:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        image_path, metadata_path = self._paths(url)
        with self._url_lock(url):
            metadata = self._read_metadata(metadata_path)
            cached: bytes | None = None
            try:
                cached = image_path.read_bytes()
            except OSError:
                pass

            now = time.time()
            if cached and float(metadata.get("expires_at", 0.0)) > now:
                return cached

            request_headers: dict[str, str] = {}
            if cached and metadata.get("etag"):
                request_headers["If-None-Match"] = str(metadata["etag"])
            if cached and metadata.get("last_modified"):
                request_headers["If-Modified-Since"] = str(metadata["last_modified"])

            try:
                response = self._session().get(
                    url,
                    headers=request_headers,
                    timeout=(3.05, 10.0),
                )
                if response.status_code == 304 and cached:
                    metadata["expires_at"] = _cache_expiry(response.headers, now)
                    self._write_metadata(metadata_path, metadata)
                    return cached
                response.raise_for_status()
                payload = response.content
                if not payload:
                    raise requests.RequestException("Map tile response was empty")
                if "no-store" not in response.headers.get("Cache-Control", "").casefold():
                    image_path.write_bytes(payload)
                    self._write_metadata(
                        metadata_path,
                        {
                            "url": url,
                            "expires_at": _cache_expiry(response.headers, now),
                            "etag": response.headers.get("ETag", ""),
                            "last_modified": response.headers.get("Last-Modified", ""),
                        },
                    )
                return payload
            except requests.RequestException:
                if cached:
                    return cached
                raise

    @staticmethod
    def _write_metadata(path: Path, metadata: dict[str, object]) -> None:
        temporary = path.with_suffix(f".{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(metadata, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)


@dataclass(frozen=True)
class TileLoadTask:
    url: str
    cancelled: Callable[[], bool]
    deliver: Callable[[bytes | None], None]


class SharedTileLoader:
    """Viewport-prioritized tile loading shared by every map widget."""

    def __init__(self, cache: HttpTileCache, *, worker_count: int = 6) -> None:
        self.cache = cache
        self._tasks: queue.PriorityQueue[tuple[float, int, TileLoadTask]] = queue.PriorityQueue()
        self._sequence = itertools.count()
        self._workers = [
            threading.Thread(target=self._work, daemon=True, name=f"map-tile-{index + 1}")
            for index in range(worker_count)
        ]
        for worker in self._workers:
            worker.start()

    def submit(self, task: TileLoadTask, *, priority: float) -> None:
        self._tasks.put((priority, next(self._sequence), task))

    def _work(self) -> None:
        while True:
            _priority, _sequence, task = self._tasks.get()
            try:
                if task.cancelled():
                    continue
                try:
                    payload = self.cache.get(task.url)
                except (OSError, requests.RequestException):
                    payload = None
                if not task.cancelled():
                    task.deliver(payload)
            finally:
                self._tasks.task_done()


_shared_loader: SharedTileLoader | None = None
_shared_loader_lock = threading.Lock()


def shared_tile_loader() -> SharedTileLoader:
    global _shared_loader
    with _shared_loader_lock:
        if _shared_loader is None:
            cache = HttpTileCache(user_cache_dir() / "map-tiles")
            _shared_loader = SharedTileLoader(cache)
        return _shared_loader
