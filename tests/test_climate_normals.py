from __future__ import annotations

import hashlib
import io
import json
import tarfile
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from rainwater_app.climate_normals import (
    BUNDLED_CATALOG_PATH,
    CLIMATE_NORMALS_PRODUCT_VERSION,
    ClimateNormalRequestCancelled,
    _NceiClientPool,
    _NceiKeepAliveClient,
    _catalog_from_noaa_sources,
    _normal_records_from_payload,
    _read_bundled_catalog,
    _request_station_normal_from_mirrors,
    _request_annual_normal_payload,
    climate_normals_bulk_archive_installed,
    climate_normals_bulk_archive_path,
    download_climate_normals_bulk_archive,
    fetch_annual_precipitation_normal,
    fetch_us_annual_precipitation_normal_catalog,
    filter_climate_normal_stations,
    remove_climate_normals_bulk_archive,
)


@pytest.fixture(autouse=True)
def isolate_bundled_and_mirror_sources(monkeypatch) -> None:
    monkeypatch.setattr(
        "rainwater_app.climate_normals._read_bundled_catalog", lambda: None
    )
    monkeypatch.setattr(
        "rainwater_app.climate_normals._request_station_normal_from_mirrors",
        lambda *_args: None,
    )


def _normal_row(
    station_id: str,
    name: str,
    latitude: float,
    longitude: float,
    precipitation: str,
    attributes: str = "S,30",
) -> dict[str, object]:
    return {
        "STATION": station_id,
        "NAME": name,
        "LATITUDE": latitude,
        "LONGITUDE": longitude,
        "ELEVATION": 1400.0,
        "ANN-PRCP-NORMAL": precipitation,
        "ANN-PRCP-NORMAL_ATTRIBUTES": attributes,
    }


def _ghcnd_line(
    station_id: str,
    latitude: float,
    longitude: float,
    elevation: float,
    state: str,
    name: str,
) -> str:
    return (
        f"{station_id:<11} {latitude:8.4f} {longitude:9.4f} "
        f"{elevation:6.1f} {state:<2} {name:<30}"
    )


def _write_bulk_archive(
    path, station_id: str = "USW00013873", *, include_incomplete: bool = False
) -> None:
    contents = (
        '"STATION","LATITUDE","LONGITUDE","ELEVATION","NAME",'
        '"ANN-PRCP-NORMAL","DJF-PRCP-NORMAL","MAM-PRCP-NORMAL",'
        '"JJA-PRCP-NORMAL","SON-PRCP-NORMAL","comp_flag_ANN-PRCP-NORMAL",'
        '"years_ANN-PRCP-NORMAL"\n'
        f'"{station_id}","33.94773","-83.32736","239.0",'
        '"ATHENS BEN EPPS AP, GA US","48.95","13.15","11.17","13.63",'
        '"11.00","S","30"\n'
    ).encode("utf-8")
    with tarfile.open(path, mode="w:gz") as archive:
        member = tarfile.TarInfo(f"{station_id}.csv")
        member.size = len(contents)
        archive.addfile(member, io.BytesIO(contents))
        if include_incomplete:
            incomplete_contents = (
                '"STATION","LATITUDE","LONGITUDE","ELEVATION","NAME",'
                '"ANN-PRCP-NORMAL","DJF-PRCP-NORMAL","MAM-PRCP-NORMAL",'
                '"JJA-PRCP-NORMAL","SON-PRCP-NORMAL"\n'
                '"USC00041614","41.53","-120.17","1400.0",'
                '"CEDARVILLE, CA US","13.12","3.00","3.12","4.00","-9999"\n'
            ).encode("utf-8")
            incomplete_member = tarfile.TarInfo("USC00041614.csv")
            incomplete_member.size = len(incomplete_contents)
            archive.addfile(incomplete_member, io.BytesIO(incomplete_contents))


def test_normal_payload_keeps_only_valid_annual_precipitation_records() -> None:
    records = _normal_records_from_payload(
        [
            _normal_row("USC00041614", "CEDARVILLE, CA US", 41.53, -120.17, "13.12"),
            _normal_row("MISSING", "MISSING", 41.0, -120.0, "-9999"),
            {"STATION": "NO-COORDS", "ANN-PRCP-NORMAL": "10.0"},
        ]
    )

    assert records == [
        {
            "station_id": "USC00041614",
            "name": "CEDARVILLE, CA US",
            "state": "CA",
            "latitude": 41.53,
            "longitude": -120.17,
            "elevation_m": 1400.0,
            "annual_precipitation_inches": 13.12,
            "attributes": "S,30",
            "completeness": "Standard",
            "period": "1991-2020",
            "provider": "NOAA NCEI U.S. Climate Normals",
        }
    ]


def test_normal_payload_reads_inline_completeness_attributes() -> None:
    row = _normal_row("INLINE", "INLINE", 40.0, -75.0, "18.25,R,16", "")

    record = _normal_records_from_payload([row])[0]

    assert record["annual_precipitation_inches"] == pytest.approx(18.25)
    assert record["attributes"] == "R,16"
    assert record["completeness"] == "Representative"


def test_catalog_joins_quick_access_names_to_noaa_station_coordinates() -> None:
    bundle = (
        'x=[["CEDARVILLE","USC00041614"],'
        '["SPRINGFIELD AP","USW00093822"],'
        '["TERRITORY","USW00099999"]]'
    )
    inventory = "\n".join(
        [
            _ghcnd_line("USC00041614", 41.53, -120.17, 1400.0, "CA", "CEDARVILLE"),
            _ghcnd_line("USW00093822", 39.84, -89.68, 181.0, "IL", "SPRINGFIELD"),
            _ghcnd_line("USW00099999", 13.48, 144.80, 75.0, "GU", "TERRITORY"),
        ]
    )

    catalog = _catalog_from_noaa_sources(bundle, inventory)

    assert [record["station_id"] for record in catalog] == [
        "USC00041614",
        "USW00093822",
    ]
    assert catalog[0]["state"] == "CA"
    assert catalog[0]["latitude"] == pytest.approx(41.53)
    assert catalog[0]["longitude"] == pytest.approx(-120.17)


def test_bundled_catalog_matches_expected_product_version() -> None:
    catalog = _read_bundled_catalog(BUNDLED_CATALOG_PATH)

    assert catalog is not None
    assert len(catalog) == 14_905
    athens = next(
        record for record in catalog if record["station_id"] == "USW00013873"
    )
    assert athens["name"] == "ATHENS BEN EPPS AP"
    assert athens["state"] == "GA"


def test_station_file_mirrors_fail_over_and_parse_official_fields(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    progress: list[str] = []

    def fake_request(url: str, timeout: int, _cancel_event):
        calls.append((url, timeout))
        if "blob.core.windows.net" in url:
            raise TimeoutError("slow mirror")
        return {
            "STATION": "USW00013873",
            "ANN-PRCP-NORMAL": "48.95",
            "DJF-PRCP-NORMAL": "13.15",
            "MAM-PRCP-NORMAL": "11.17",
            "JJA-PRCP-NORMAL": "13.63",
            "SON-PRCP-NORMAL": "11.00",
            "comp_flag_ANN-PRCP-NORMAL": "S",
            "years_ANN-PRCP-NORMAL": "30",
        }

    monkeypatch.setattr(
        "rainwater_app.climate_normals._request_station_csv_row", fake_request
    )

    result = _request_station_normal_from_mirrors(
        "USW00013873", progress.append, None
    )

    assert result is not None
    values, attributes, provider = result
    assert values["annual_precipitation_inches"] == pytest.approx(48.95)
    assert values["autumn_precipitation_inches"] == pytest.approx(11.0)
    assert attributes == "S,30"
    assert provider == "NOAA AWS mirror"
    assert len(calls) == 2
    assert calls[0][1] == 8
    assert calls[1][1] == 8
    assert progress == [
        "Connecting to NOAA Azure mirror (timeout 8 seconds)...",
        "Connecting to NOAA AWS mirror (timeout 8 seconds)...",
    ]


def test_fetch_annual_precipitation_normal_uses_request_and_persistent_cache(
    monkeypatch, tmp_path
) -> None:
    captured_url = ""
    request_count = 0

    def fake_request(url: str, _progress_callback):
        nonlocal captured_url, request_count
        captured_url = url
        request_count += 1
        return [
            {
                "STATION": "USC00041614",
                "ANN-PRCP-NORMAL": "13.12",
                "DJF-PRCP-NORMAL": "3.00",
                "MAM-PRCP-NORMAL": "3.12",
                "JJA-PRCP-NORMAL": "4.00",
                "SON-PRCP-NORMAL": "3.00",
            }
        ]

    monkeypatch.setattr(
        "rainwater_app.climate_normals._request_annual_normal_payload", fake_request
    )
    station = {
        "station_id": "USC00041614",
        "name": "CEDARVILLE",
        "state": "CA",
        "latitude": 41.53,
        "longitude": -120.17,
    }
    (tmp_path / "noaa_normals_1991_2020_annual_values.json").write_text(
        '{"USC00041614":{"annual_precipitation_inches":13.12,'
        '"cached_at":9999999999}}',
        encoding="utf-8",
    )
    record = fetch_annual_precipitation_normal(station, cache_dir=tmp_path)
    cached_record = fetch_annual_precipitation_normal(station, cache_dir=tmp_path)
    query = parse_qs(urlparse(captured_url).query)

    assert record["annual_precipitation_inches"] == pytest.approx(13.12)
    assert record["winter_precipitation_inches"] == pytest.approx(3.0)
    assert record["spring_precipitation_inches"] == pytest.approx(3.12)
    assert record["summer_precipitation_inches"] == pytest.approx(4.0)
    assert record["autumn_precipitation_inches"] == pytest.approx(3.0)
    assert cached_record["annual_precipitation_inches"] == pytest.approx(13.12)
    assert record["name"] == "CEDARVILLE"
    assert request_count == 1
    assert query["stations"] == ["USC00041614"]
    assert query["dataTypes"] == [
        "ANN-PRCP-NORMAL,DJF-PRCP-NORMAL,MAM-PRCP-NORMAL,"
        "JJA-PRCP-NORMAL,SON-PRCP-NORMAL"
    ]
    assert "includeStationName" not in query
    assert "includeStationLocation" not in query

    cache_payload = json.loads(
        (tmp_path / "noaa_normals_1991_2020_annual_values.json").read_text(
            encoding="utf-8"
        )
    )
    assert cache_payload["product_version"] == CLIMATE_NORMALS_PRODUCT_VERSION
    assert cache_payload["stations"]["USC00041614"]["status"] == "ok"


def test_value_cache_is_invalidated_when_product_version_changes(
    monkeypatch, tmp_path
) -> None:
    cache_path = tmp_path / "noaa_normals_1991_2020_annual_values.json"
    cache_path.write_text(
        json.dumps(
            {
                "product_version": "obsolete-version",
                "stations": {
                    "USC00041614": {
                        "status": "ok",
                        "annual_precipitation_inches": 999.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "rainwater_app.climate_normals._request_annual_normal_payload",
        lambda *_args: [
            {
                "STATION": "USC00041614",
                "ANN-PRCP-NORMAL": "13.12",
                "DJF-PRCP-NORMAL": "3.00",
                "MAM-PRCP-NORMAL": "3.12",
                "JJA-PRCP-NORMAL": "4.00",
                "SON-PRCP-NORMAL": "3.00",
            }
        ],
    )
    station = {"station_id": "USC00041614", "name": "CEDARVILLE"}

    record = fetch_annual_precipitation_normal(station, cache_dir=tmp_path)

    assert record["annual_precipitation_inches"] == pytest.approx(13.12)
    refreshed = json.loads(cache_path.read_text(encoding="utf-8"))
    assert refreshed["product_version"] == CLIMATE_NORMALS_PRODUCT_VERSION
    assert refreshed["stations"]["USC00041614"]["annual_precipitation_inches"] == 13.12


def test_fetch_annual_normal_uses_installed_bulk_archive_before_api(
    monkeypatch, tmp_path
) -> None:
    archive_path = climate_normals_bulk_archive_path(tmp_path)
    _write_bulk_archive(archive_path)
    monkeypatch.setattr(
        "rainwater_app.climate_normals.NCEI_BULK_ARCHIVE_SIZE_BYTES",
        archive_path.stat().st_size,
    )
    monkeypatch.setattr(
        "rainwater_app.climate_normals._request_annual_normal_payload",
        lambda *_args: pytest.fail("online lookup should not run"),
    )
    station = {
        "station_id": "USW00013873",
        "name": "ATHENS BEN EPPS AP",
        "state": "GA",
        "latitude": 33.94773,
        "longitude": -83.32736,
    }

    record = fetch_annual_precipitation_normal(station, cache_dir=tmp_path)

    assert record["annual_precipitation_inches"] == pytest.approx(48.95)
    assert record["winter_precipitation_inches"] == pytest.approx(13.15)
    assert record["spring_precipitation_inches"] == pytest.approx(11.17)
    assert record["summer_precipitation_inches"] == pytest.approx(13.63)
    assert record["autumn_precipitation_inches"] == pytest.approx(11.0)
    assert record["attributes"] == "S,30"
    assert record["completeness"] == "Standard"
    assert record["provider"].endswith("(local bulk archive fallback)")


def test_catalog_can_be_built_offline_from_installed_bulk_archive(
    monkeypatch, tmp_path
) -> None:
    archive_path = climate_normals_bulk_archive_path(tmp_path)
    _write_bulk_archive(archive_path)
    monkeypatch.setattr(
        "rainwater_app.climate_normals.NCEI_BULK_ARCHIVE_SIZE_BYTES",
        archive_path.stat().st_size,
    )
    monkeypatch.setattr(
        "rainwater_app.climate_normals._get_json",
        lambda *_args: pytest.fail("online catalog lookup should not run"),
    )

    catalog = fetch_us_annual_precipitation_normal_catalog(cache_dir=tmp_path)

    assert catalog == [
        {
            "station_id": "USW00013873",
            "name": "ATHENS BEN EPPS AP",
            "state": "GA",
            "latitude": pytest.approx(33.94773),
            "longitude": pytest.approx(-83.32736),
            "elevation_m": pytest.approx(239.0),
        }
    ]


def test_installed_archive_ignores_unfiltered_online_catalog_cache(
    monkeypatch, tmp_path
) -> None:
    archive_path = climate_normals_bulk_archive_path(tmp_path)
    _write_bulk_archive(archive_path)
    monkeypatch.setattr(
        "rainwater_app.climate_normals.NCEI_BULK_ARCHIVE_SIZE_BYTES",
        archive_path.stat().st_size,
    )
    (tmp_path / "noaa_normals_1991_2020_station_catalog.json").write_text(
        '[{"station_id":"USC00000001","name":"INCOMPLETE",'
        '"state":"CA","latitude":40.0,"longitude":-120.0}]',
        encoding="utf-8",
    )

    catalog = fetch_us_annual_precipitation_normal_catalog(cache_dir=tmp_path)

    assert [record["station_id"] for record in catalog] == ["USW00013873"]
    assert (
        tmp_path / "noaa_normals_1991_2020_complete_station_catalog.json"
    ).is_file()


def test_installed_archive_catalog_excludes_station_missing_a_season(
    monkeypatch, tmp_path
) -> None:
    archive_path = climate_normals_bulk_archive_path(tmp_path)
    _write_bulk_archive(
        archive_path, station_id="USW00013873", include_incomplete=True
    )
    monkeypatch.setattr(
        "rainwater_app.climate_normals.NCEI_BULK_ARCHIVE_SIZE_BYTES",
        archive_path.stat().st_size,
    )

    catalog = fetch_us_annual_precipitation_normal_catalog(cache_dir=tmp_path)

    assert [record["station_id"] for record in catalog] == ["USW00013873"]


def test_bulk_archive_download_is_verified_and_removable(monkeypatch, tmp_path) -> None:
    archive_bytes = b"verified NOAA archive bytes"

    class FakeResponse:
        headers = {"Content-Length": str(len(archive_bytes))}

        def __init__(self) -> None:
            self.remaining = archive_bytes

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def read(self, _size: int) -> bytes:
            chunk, self.remaining = self.remaining, b""
            return chunk

    monkeypatch.setattr(
        "rainwater_app.climate_normals.NCEI_BULK_ARCHIVE_SIZE_BYTES",
        len(archive_bytes),
    )
    monkeypatch.setattr(
        "rainwater_app.climate_normals.NCEI_BULK_ARCHIVE_SHA256",
        hashlib.sha256(archive_bytes).hexdigest(),
    )
    monkeypatch.setattr(
        "rainwater_app.climate_normals.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )
    progress: list[tuple[int, int]] = []

    path = download_climate_normals_bulk_archive(
        cache_dir=tmp_path,
        progress_callback=lambda current, total: progress.append((current, total)),
    )

    assert path.read_bytes() == archive_bytes
    assert climate_normals_bulk_archive_installed(tmp_path)
    assert progress == [(len(archive_bytes), len(archive_bytes))]
    assert remove_climate_normals_bulk_archive(tmp_path)
    assert not path.exists()
    assert not remove_climate_normals_bulk_archive(tmp_path)


def test_annual_request_retries_once_with_progress(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    progress: list[str] = []

    def fake_get_json(url: str, timeout: int):
        calls.append((url, timeout))
        if len(calls) == 1:
            raise TimeoutError("slow handshake")
        return [{"STATION": "USC00041614", "ANN-PRCP-NORMAL": "13.12"}]

    monkeypatch.setattr(
        "rainwater_app.climate_normals.ANNUAL_REQUEST_TIMEOUTS_SECONDS", (3, 2)
    )
    monkeypatch.setattr(
        "rainwater_app.climate_normals._annual_normal_http_client.get_json",
        fake_get_json,
    )

    payload = _request_annual_normal_payload("https://www.ncei.noaa.gov/test", progress.append)

    assert isinstance(payload, list)
    assert calls == [
        ("https://www.ncei.noaa.gov/test", 3),
        ("https://www.ncei.noaa.gov/test", 2),
    ]
    assert progress == [
        "Connecting to NOAA (attempt 1 of 2; timeout 3 seconds)...",
        "NOAA did not respond; retrying once...",
        "Connecting to NOAA (attempt 2 of 2; timeout 2 seconds)...",
    ]


def test_annual_request_stops_before_network_when_cancelled(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    cancel_event = threading.Event()
    cancel_event.set()
    monkeypatch.setattr(
        "rainwater_app.climate_normals._annual_normal_http_client.get_json",
        lambda url, timeout, event: calls.append((url, timeout)),
    )

    with pytest.raises(ClimateNormalRequestCancelled):
        _request_annual_normal_payload(
            "https://www.ncei.noaa.gov/test", None, cancel_event
        )

    assert calls == []


def test_confirmed_unavailable_station_is_cached_briefly(monkeypatch, tmp_path) -> None:
    request_count = 0

    def no_data(*_args):
        nonlocal request_count
        request_count += 1
        return []

    monkeypatch.setattr(
        "rainwater_app.climate_normals._request_annual_normal_payload", no_data
    )
    station = {"station_id": "USC00041614", "name": "CEDARVILLE"}

    with pytest.raises(ValueError, match="no annual precipitation normal"):
        fetch_annual_precipitation_normal(station, cache_dir=tmp_path)
    with pytest.raises(ValueError, match="no annual precipitation normal"):
        fetch_annual_precipitation_normal(station, cache_dir=tmp_path)

    assert request_count == 1


def test_ncei_client_pool_distributes_requests_across_four_clients(monkeypatch) -> None:
    calls: list[tuple[int, str]] = []
    pool = _NceiClientPool(size=4)
    for index, client in enumerate(pool._clients):
        monkeypatch.setattr(
            client,
            "get_json",
            lambda url, _timeout, _event=None, index=index: calls.append((index, url)),
        )

    for request_index in range(5):
        pool.get_json(f"https://www.ncei.noaa.gov/{request_index}", 5)

    assert [index for index, _url in calls] == [0, 1, 2, 3, 0]


def test_keep_alive_client_reuses_connection(monkeypatch) -> None:
    connections = []

    class FakeResponse:
        status = 200
        will_close = False

        @staticmethod
        def read() -> bytes:
            return b'[{"ok": true}]'

    class FakeConnection:
        def __init__(self, host: str, port: int, timeout: int):
            self.host = host
            self.port = port
            self.timeout = timeout
            self.sock = None
            self.requests = []
            connections.append(self)

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            self.requests.append((method, path, headers))

        @staticmethod
        def getresponse() -> FakeResponse:
            return FakeResponse()

        @staticmethod
        def close() -> None:
            pass

    monkeypatch.setattr(
        "rainwater_app.climate_normals.http.client.HTTPSConnection", FakeConnection
    )
    client = _NceiKeepAliveClient()

    client.get_json("https://www.ncei.noaa.gov/first", 10)
    client.get_json("https://www.ncei.noaa.gov/second?x=1", 5)

    assert len(connections) == 1
    assert connections[0].timeout == 5
    assert [request[1] for request in connections[0].requests] == [
        "/first",
        "/second?x=1",
    ]


def test_station_filter_searches_names_nationwide_and_can_filter_by_state() -> None:
    records = [
        {"station_id": "CA1", "name": "SPRINGFIELD NORTH", "state": "CA"},
        {"station_id": "IL1", "name": "SPRINGFIELD AP", "state": "IL"},
        {"station_id": "CA2", "name": "ZEPHYR", "state": "CA"},
    ]

    nationwide = filter_climate_normal_stations(records, name_query="springfield")
    california = filter_climate_normal_stations(records, state_code="ca")

    assert [record["station_id"] for record in nationwide] == ["IL1", "CA1"]
    assert [record["station_id"] for record in california] == ["CA1", "CA2"]


def test_catalog_fetch_is_cached(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    bundle_url = "https://www.ncei.noaa.gov/access/us-climate-normals/static/js/main.js"
    bundle = 'x=[["CEDARVILLE","USC00041614"]]'
    inventory = _ghcnd_line(
        "USC00041614", 41.53, -120.17, 1400.0, "CA", "CEDARVILLE"
    )

    monkeypatch.setattr(
        "rainwater_app.climate_normals._get_json",
        lambda _url: {"files": {"main.js": "/access/us-climate-normals/static/js/main.js"}},
    )

    def fake_get_text(url: str) -> str:
        calls.append(url)
        return bundle if url == bundle_url else inventory

    monkeypatch.setattr("rainwater_app.climate_normals._get_text", fake_get_text)

    first = fetch_us_annual_precipitation_normal_catalog(cache_dir=tmp_path)
    second = fetch_us_annual_precipitation_normal_catalog(cache_dir=tmp_path)

    assert first == second
    assert first[0]["station_id"] == "USC00041614"
    assert sorted(calls) == sorted(
        [bundle_url, "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"]
    )
