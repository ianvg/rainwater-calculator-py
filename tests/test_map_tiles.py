from __future__ import annotations

import time

import requests

from rainwater_app.map_tiles import DEFAULT_TILE_CACHE_SECONDS, HttpTileCache, _cache_expiry


class _Response:
    def __init__(
        self,
        content: bytes,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(
        self, url: str, *, headers: dict[str, str], timeout: tuple[float, float]
    ) -> _Response:
        assert timeout == (3.05, 10.0)
        self.calls.append((url, headers))
        return self.responses.pop(0)


def test_cache_expiry_honors_max_age_and_has_seven_day_fallback() -> None:
    now = 1_000.0
    assert _cache_expiry(
        requests.structures.CaseInsensitiveDict({"Cache-Control": "public, max-age=3600"}),
        now,
    ) == 4_600.0
    assert _cache_expiry(requests.structures.CaseInsensitiveDict(), now) == (
        now + DEFAULT_TILE_CACHE_SECONDS
    )


def test_http_tile_cache_reuses_fresh_response_without_network(tmp_path, monkeypatch) -> None:
    tile_cache = HttpTileCache(tmp_path)
    session = _Session([_Response(b"tile", headers={"Cache-Control": "max-age=3600"})])
    monkeypatch.setattr(tile_cache, "_session", lambda: session)

    assert tile_cache.get("https://tiles.example/1/2/3.png") == b"tile"
    assert tile_cache.get("https://tiles.example/1/2/3.png") == b"tile"
    assert len(session.calls) == 1


def test_http_tile_cache_revalidates_expired_response(tmp_path, monkeypatch) -> None:
    tile_cache = HttpTileCache(tmp_path)
    session = _Session(
        [
            _Response(
                b"tile",
                headers={"Cache-Control": "max-age=0", "ETag": '"tile-1"'},
            ),
            _Response(b"", status_code=304, headers={"Cache-Control": "max-age=3600"}),
        ]
    )
    monkeypatch.setattr(tile_cache, "_session", lambda: session)

    assert tile_cache.get("https://tiles.example/1/2/3.png") == b"tile"
    time.sleep(0.001)
    assert tile_cache.get("https://tiles.example/1/2/3.png") == b"tile"
    assert session.calls[1][1] == {"If-None-Match": '"tile-1"'}
