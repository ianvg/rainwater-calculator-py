from __future__ import annotations

import csv
import hashlib
import http.client
import io
import json
import os
import re
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request
from urllib.parse import urljoin, urlsplit

from .app_paths import user_cache_dir

NCEI_ACCESS_DATA_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
NCEI_CLIMATE_NORMALS_ROOT = "https://www.ncei.noaa.gov/access/us-climate-normals/"
NCEI_CLIMATE_NORMALS_URL = (
    f"{NCEI_CLIMATE_NORMALS_ROOT}#dataset=normals-annualseasonal&timeframe=30"
)
NCEI_ASSET_MANIFEST_URL = f"{NCEI_CLIMATE_NORMALS_ROOT}asset-manifest.json"
NCEI_GHCND_STATIONS_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
NCEI_BULK_ARCHIVE_NAME = (
    "us-climate-normals_1991-2020_v1.0.1_annualseasonal_"
    "multivariate_by-station_c20230404.tar.gz"
)
# NOAA publishes the same authoritative archive through its public AWS Open Data mirror.
# The mirror avoids the unusually slow TLS negotiation some users experience with NCEI.
NCEI_BULK_ARCHIVE_URL = (
    "https://noaa-normals-pds.s3.amazonaws.com/"
    "normals-annualseasonal/1991-2020/archive/"
    f"{NCEI_BULK_ARCHIVE_NAME}"
)
NCEI_BULK_ARCHIVE_SIZE_BYTES = 54_176_270
NCEI_BULK_ARCHIVE_SHA256 = (
    "0fdb814203150780d4ee0c5d53c7844a237a21881101fb7d922b0aa3a1fd190f"
)
CLIMATE_NORMALS_DATASET = "normals-annualseasonal-1991-2020"
ANNUAL_PRECIPITATION_FIELD = "ANN-PRCP-NORMAL"
PRECIPITATION_NORMAL_FIELDS = (
    ("annual", ANNUAL_PRECIPITATION_FIELD),
    ("winter", "DJF-PRCP-NORMAL"),
    ("spring", "MAM-PRCP-NORMAL"),
    ("summer", "JJA-PRCP-NORMAL"),
    ("autumn", "SON-PRCP-NORMAL"),
)
PRECIPITATION_NORMAL_RECORD_KEYS = tuple(
    f"{season}_precipitation_inches" for season, _field in PRECIPITATION_NORMAL_FIELDS
)
USER_AGENT = "RWH-Calculator/0.1.2 (+https://github.com/ianvg/rainwater-calculator-py)"
_STATION_ID_PATTERN = re.compile(r"[A-Z0-9]{11}", re.IGNORECASE)
_QUICK_ACCESS_STATION_PATTERN = re.compile(
    r'\["((?:[^"\\]|\\.)*)","(US[A-Z0-9]{9})"\]'
)
DEFAULT_CACHE_DIR = user_cache_dir() / "weather"
CATALOG_CACHE_NAME = "noaa_normals_1991_2020_station_catalog.json"
BULK_CATALOG_CACHE_NAME = "noaa_normals_1991_2020_complete_station_catalog.json"
CATALOG_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
ANNUAL_VALUE_CACHE_NAME = "noaa_normals_1991_2020_annual_values.json"
ANNUAL_VALUE_CACHE_MAX_AGE_SECONDS = 365 * 24 * 60 * 60
ANNUAL_REQUEST_TIMEOUTS_SECONDS = (105, 60)
US_STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS "
    "MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
_annual_value_cache_lock = threading.Lock()


class _NceiKeepAliveClient:
    """Serialize small NCEI requests over a reusable HTTPS connection."""

    def __init__(self) -> None:
        self._connection: http.client.HTTPSConnection | None = None
        self._lock = threading.Lock()

    def get_json(self, url: str, timeout: int) -> object:
        target = urlsplit(url)
        if target.scheme != "https" or not target.hostname:
            raise ValueError("NOAA request URL must use HTTPS.")
        path = target.path or "/"
        if target.query:
            path = f"{path}?{target.query}"
        with self._lock:
            connection = self._connection
            if connection is None or connection.host != target.hostname:
                self._close_unlocked()
                connection = http.client.HTTPSConnection(
                    target.hostname, target.port or 443, timeout=timeout
                )
                self._connection = connection
            else:
                connection.timeout = timeout
                if connection.sock is not None:
                    connection.sock.settimeout(timeout)
            try:
                connection.request(
                    "GET",
                    path,
                    headers={
                        "Accept": "application/json",
                        "Connection": "keep-alive",
                        "User-Agent": USER_AGENT,
                    },
                )
                response = connection.getresponse()
                body = response.read().decode("utf-8")
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"NOAA request failed (HTTP {response.status}).")
                if response.will_close:
                    self._close_unlocked()
                return json.loads(body)
            except json.JSONDecodeError as exc:
                self._close_unlocked()
                raise ValueError("NOAA returned an invalid JSON response.") from exc
            except (OSError, http.client.HTTPException):
                self._close_unlocked()
                raise

    def close(self) -> None:
        with self._lock:
            self._close_unlocked()

    def _close_unlocked(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except OSError:
                pass
        self._connection = None


_annual_normal_http_client = _NceiKeepAliveClient()


def climate_normals_bulk_archive_path(cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    """Return the managed location of the optional NOAA bulk archive."""
    return cache_dir / NCEI_BULK_ARCHIVE_NAME


def climate_normals_bulk_archive_installed(
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> bool:
    """Return whether the complete optional archive is present locally."""
    path = climate_normals_bulk_archive_path(cache_dir)
    try:
        return path.is_file() and path.stat().st_size == NCEI_BULK_ARCHIVE_SIZE_BYTES
    except OSError:
        return False


def download_climate_normals_bulk_archive(
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    """Download and verify NOAA's optional annual/seasonal normals archive.

    The completed file is moved into place atomically, so interrupted downloads never
    replace a previously valid archive.
    """
    destination = climate_normals_bulk_archive_path(cache_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.download")
    digest = hashlib.sha256()
    downloaded = 0
    try:
        temporary.unlink(missing_ok=True)
        req = request.Request(
            NCEI_BULK_ARCHIVE_URL,
            headers={"Accept": "application/gzip", "User-Agent": USER_AGENT},
        )
        with request.urlopen(req, timeout=180) as response, temporary.open("wb") as output:
            total = _content_length(response) or NCEI_BULK_ARCHIVE_SIZE_BYTES
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if progress_callback is not None:
                    progress_callback(downloaded, total)
        if downloaded != NCEI_BULK_ARCHIVE_SIZE_BYTES:
            raise ValueError(
                "The NOAA Climate Normals archive download was incomplete "
                f"({downloaded:,} of {NCEI_BULK_ARCHIVE_SIZE_BYTES:,} bytes)."
            )
        if digest.hexdigest().casefold() != NCEI_BULK_ARCHIVE_SHA256.casefold():
            raise ValueError("The NOAA Climate Normals archive failed its SHA-256 check.")
        os.replace(temporary, destination)
        return destination
    except error.HTTPError as exc:
        raise RuntimeError(f"NOAA archive download failed (HTTP {exc.code}).") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Could not download the NOAA archive: {exc.reason}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def remove_climate_normals_bulk_archive(
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> bool:
    """Remove only the optional bulk archive, retaining ordinary station caches."""
    path = climate_normals_bulk_archive_path(cache_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def fetch_us_annual_precipitation_normal_catalog(
    cache_dir: Path = DEFAULT_CACHE_DIR,
    max_age_seconds: int = CATALOG_CACHE_MAX_AGE_SECONDS,
) -> list[dict[str, Any]]:
    """Return the mapped U.S. station catalog used by NOAA Quick Access.

    Quick Access embeds its station names and identifiers in its current application bundle.
    Coordinates and state codes are joined from NOAA's authoritative GHCN-D station inventory.
    The merged catalog is cached so subsequent browsing and name filtering are local.
    """
    archive_installed = climate_normals_bulk_archive_installed(cache_dir)
    cache_path = cache_dir / (
        BULK_CATALOG_CACHE_NAME if archive_installed else CATALOG_CACHE_NAME
    )
    if _cache_is_current(cache_path, max_age_seconds):
        cached = _read_catalog_cache(cache_path)
        if cached is not None:
            return cached

    if archive_installed:
        catalog = _catalog_from_bulk_archive(
            climate_normals_bulk_archive_path(cache_dir)
        )
        if not catalog:
            raise ValueError(
                "The installed NOAA Climate Normals archive contains no mappable U.S. stations."
            )
        _write_catalog_cache(cache_path, catalog)
        return catalog

    manifest = _get_json(NCEI_ASSET_MANIFEST_URL)
    bundle_url = _quick_access_bundle_url(manifest)
    with ThreadPoolExecutor(max_workers=2) as executor:
        bundle_future = executor.submit(_get_text, bundle_url)
        stations_future = executor.submit(_get_text, NCEI_GHCND_STATIONS_URL)
        catalog = _catalog_from_noaa_sources(
            bundle_future.result(), stations_future.result()
        )
    if not catalog:
        raise ValueError("NOAA returned no mappable 1991-2020 Climate Normals stations.")
    _write_catalog_cache(cache_path, catalog)
    return catalog


def fetch_annual_precipitation_normal(
    station: dict[str, Any],
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Return one station's NOAA 1991-2020 annual and seasonal precipitation normals."""
    station_id = str(station.get("station_id") or "").strip().upper()
    if not _STATION_ID_PATTERN.fullmatch(station_id):
        raise ValueError("The selected NOAA station identifier is invalid.")
    cached_values = _read_cached_precipitation_values(cache_dir, station_id)
    if cached_values is not None:
        return _annual_normal_record(station, station_id, cached_values)
    archived_record = _read_annual_normal_from_bulk_archive(cache_dir, station_id)
    if archived_record is not None:
        precipitation_values, attributes = archived_record
        _cache_precipitation_values(cache_dir, station_id, precipitation_values)
        return _annual_normal_record(
            station,
            station_id,
            precipitation_values,
            attributes=attributes,
            provider="NOAA NCEI U.S. Climate Normals (local bulk archive)",
        )
    parameters = {
        "dataset": CLIMATE_NORMALS_DATASET,
        "stations": station_id,
        "format": "json",
        "dataTypes": ",".join(field for _season, field in PRECIPITATION_NORMAL_FIELDS),
    }
    url = f"{NCEI_ACCESS_DATA_URL}?{parse.urlencode(parameters)}"
    payload = _request_annual_normal_payload(url, progress_callback)
    if isinstance(payload, dict) and payload.get("errorMessage"):
        raise RuntimeError(str(payload["errorMessage"]))
    if not isinstance(payload, list) or not payload:
        raise ValueError("NOAA returned no annual precipitation normal for this station.")
    matching_row = next(
        (
            row
            for row in payload
            if isinstance(row, dict)
            and str(row.get("STATION") or "").strip().upper() == station_id
        ),
        None,
    )
    if matching_row is None:
        raise ValueError("NOAA returned no annual precipitation normal for this station.")
    precipitation_values = _precipitation_values_from_row(matching_row)
    if precipitation_values is None:
        raise ValueError(
            "This station does not have a complete set of 1991-2020 annual and "
            "seasonal precipitation normals."
        )
    _cache_precipitation_values(cache_dir, station_id, precipitation_values)
    return _annual_normal_record(station, station_id, precipitation_values)


def _annual_normal_record(
    station: dict[str, Any],
    station_id: str,
    precipitation_values: dict[str, float],
    *,
    attributes: str = "",
    provider: str = "NOAA NCEI U.S. Climate Normals",
) -> dict[str, Any]:
    result = dict(station)
    result.update(
        {
            "station_id": station_id,
            "attributes": attributes,
            "completeness": _completeness_label(attributes),
            "period": "1991-2020",
            "provider": provider,
        }
    )
    result.update(precipitation_values)
    return result


def _read_annual_normal_from_bulk_archive(
    cache_dir: Path, station_id: str
) -> tuple[dict[str, float], str] | None:
    archive_path = climate_normals_bulk_archive_path(cache_dir)
    if not climate_normals_bulk_archive_installed(cache_dir):
        return None
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            try:
                member = archive.getmember(f"{station_id}.csv")
            except KeyError:
                member = next(
                    item
                    for item in archive.getmembers()
                    if Path(item.name).stem.casefold() == station_id.casefold()
                    and item.name.casefold().endswith(".csv")
                )
            source = archive.extractfile(member)
            if source is None:
                return None
            with source, io.TextIOWrapper(source, encoding="utf-8-sig", newline="") as text:
                row = next(csv.DictReader(text), None)
    except (KeyError, StopIteration, OSError, tarfile.TarError, csv.Error, UnicodeError):
        return None
    if not isinstance(row, dict):
        return None
    precipitation_values = _precipitation_values_from_row(row)
    if precipitation_values is None:
        return None
    completeness = str(row.get(f"comp_flag_{ANNUAL_PRECIPITATION_FIELD}") or "").strip()
    years = str(row.get(f"years_{ANNUAL_PRECIPITATION_FIELD}") or "").strip()
    attributes = ",".join(part for part in (completeness, years) if part)
    return precipitation_values, attributes


def _precipitation_values_from_row(row: dict[str, Any]) -> dict[str, float] | None:
    values: dict[str, float] = {}
    for season, field in PRECIPITATION_NORMAL_FIELDS:
        value = _number(row.get(field))
        if value is None:
            return None
        values[f"{season}_precipitation_inches"] = value
    return values


def _request_annual_normal_payload(
    url: str, progress_callback: Callable[[str], None] | None
) -> object:
    last_error: Exception | None = None
    attempt_count = len(ANNUAL_REQUEST_TIMEOUTS_SECONDS)
    for attempt, timeout in enumerate(ANNUAL_REQUEST_TIMEOUTS_SECONDS, start=1):
        if progress_callback is not None:
            progress_callback(
                f"Connecting to NOAA (attempt {attempt} of {attempt_count}; "
                f"timeout {timeout} seconds)..."
            )
        try:
            return _annual_normal_http_client.get_json(url, timeout)
        except (OSError, http.client.HTTPException, RuntimeError) as exc:
            last_error = exc
            if attempt < attempt_count and progress_callback is not None:
                progress_callback("NOAA did not respond; retrying once...")
    raise RuntimeError(
        "NOAA did not respond after two attempts. Try the station again later."
    ) from last_error


def filter_climate_normal_stations(
    records: list[dict[str, Any]], *, name_query: str = "", state_code: str = ""
) -> list[dict[str, Any]]:
    """Filter and alphabetize Climate Normals stations for the station browser."""
    query = name_query.strip().casefold()
    state = state_code.strip().upper()
    filtered = [
        record
        for record in records
        if (not query or query in str(record.get("name", "")).casefold())
        and (not state or record.get("state") == state)
    ]
    return sorted(
        filtered,
        key=lambda item: (
            str(item.get("name", "")).casefold(),
            str(item.get("station_id", "")),
        ),
    )


def _quick_access_bundle_url(manifest: object) -> str:
    if not isinstance(manifest, dict):
        raise ValueError("NOAA returned an invalid Quick Access asset manifest.")
    files = manifest.get("files")
    main_path = files.get("main.js") if isinstance(files, dict) else None
    if not isinstance(main_path, str) or not main_path.strip():
        raise ValueError("NOAA's Quick Access station catalog could not be located.")
    return urljoin(NCEI_CLIMATE_NORMALS_ROOT, main_path)


def _catalog_from_noaa_sources(
    quick_access_bundle: str, ghcnd_station_inventory: str
) -> list[dict[str, Any]]:
    quick_names: dict[str, str] = {}
    for encoded_name, station_id in _QUICK_ACCESS_STATION_PATTERN.findall(
        quick_access_bundle
    ):
        try:
            station_name = json.loads(f'"{encoded_name}"').strip()
        except json.JSONDecodeError:
            continue
        if station_name:
            quick_names.setdefault(station_id, station_name)

    catalog: list[dict[str, Any]] = []
    for line in ghcnd_station_inventory.splitlines():
        if len(line) < 71:
            continue
        station_id = line[0:11].strip()
        if station_id not in quick_names:
            continue
        state = line[38:40].strip().upper()
        if state not in US_STATE_CODES:
            continue
        latitude = _number(line[12:20])
        longitude = _number(line[21:30])
        if latitude is None or longitude is None:
            continue
        catalog.append(
            {
                "station_id": station_id,
                "name": quick_names[station_id],
                "state": state,
                "latitude": latitude,
                "longitude": longitude,
                "elevation_m": _number(line[31:37]),
            }
        )
    return filter_climate_normal_stations(catalog)


def _catalog_from_bulk_archive(archive_path: Path) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive:
                if not member.isfile() or not member.name.casefold().endswith(".csv"):
                    continue
                source = archive.extractfile(member)
                if source is None:
                    continue
                with source, io.TextIOWrapper(
                    source, encoding="utf-8-sig", newline=""
                ) as text:
                    row = next(csv.DictReader(text), None)
                if not isinstance(row, dict):
                    continue
                station_id = str(row.get("STATION") or Path(member.name).stem).strip()
                name = str(row.get("NAME") or station_id).strip()
                state = _station_state_code(row, name)
                latitude = _number(row.get("LATITUDE"))
                longitude = _number(row.get("LONGITUDE"))
                precipitation_values = _precipitation_values_from_row(row)
                if (
                    not _STATION_ID_PATTERN.fullmatch(station_id)
                    or state not in US_STATE_CODES
                    or latitude is None
                    or longitude is None
                    or precipitation_values is None
                ):
                    continue
                catalog.append(
                    {
                        "station_id": station_id,
                        "name": re.sub(rf",\s*{state}\s+US\s*$", "", name).strip(),
                        "state": state,
                        "latitude": latitude,
                        "longitude": longitude,
                        "elevation_m": _number(row.get("ELEVATION")),
                    }
                )
    except (OSError, tarfile.TarError, csv.Error, UnicodeError) as exc:
        raise ValueError("The installed NOAA Climate Normals archive is invalid.") from exc
    return filter_climate_normal_stations(catalog)


def _normal_records_from_payload(payload: object) -> list[dict[str, Any]]:
    """Parse fully attributed Climate Normals rows used by tests and saved caches."""
    if isinstance(payload, dict) and payload.get("errorMessage"):
        raise RuntimeError(str(payload["errorMessage"]))
    if not isinstance(payload, list):
        raise ValueError("NOAA returned an unexpected Climate Normals response.")

    records: list[dict[str, Any]] = []
    seen_station_ids: set[str] = set()
    for row in payload:
        if not isinstance(row, dict):
            continue
        station_id = str(row.get("STATION") or row.get("station") or "").strip()
        if not station_id or station_id in seen_station_ids:
            continue
        raw_precipitation = row.get(ANNUAL_PRECIPITATION_FIELD)
        precipitation = _number(raw_precipitation)
        latitude = _number(row.get("LATITUDE"))
        longitude = _number(row.get("LONGITUDE"))
        if precipitation is None or latitude is None or longitude is None:
            continue
        attributes = str(
            row.get(f"{ANNUAL_PRECIPITATION_FIELD}_ATTRIBUTES")
            or row.get(f"{ANNUAL_PRECIPITATION_FIELD}-ATTRIBUTES")
            or ""
        ).strip()
        if not attributes and isinstance(raw_precipitation, str) and "," in raw_precipitation:
            attributes = raw_precipitation.split(",", 1)[1].strip()
        name = str(row.get("NAME") or row.get("STATION_NAME") or station_id).strip()
        records.append(
            {
                "station_id": station_id,
                "name": name,
                "state": _station_state_code(row, name),
                "latitude": latitude,
                "longitude": longitude,
                "elevation_m": _number(row.get("ELEVATION")),
                "annual_precipitation_inches": precipitation,
                "attributes": attributes,
                "completeness": _completeness_label(attributes),
                "period": "1991-2020",
                "provider": "NOAA NCEI U.S. Climate Normals",
            }
        )
        seen_station_ids.add(station_id)
    return filter_climate_normal_stations(records)


def _station_state_code(row: dict[str, Any], name: str) -> str:
    explicit_state = str(row.get("STATE") or row.get("state") or "").strip().upper()
    if explicit_state in US_STATE_CODES:
        return explicit_state
    match = re.search(r",\s*([A-Z]{2})\s+US\s*$", name.upper())
    return match.group(1) if match and match.group(1) in US_STATE_CODES else ""


def _number(value: object) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).strip())
    if not match:
        return None
    parsed = float(match.group(0))
    return None if parsed == -9999 else parsed


def _content_length(response: object) -> int | None:
    try:
        value = response.headers.get("Content-Length")  # type: ignore[attr-defined]
        return int(value) if value else None
    except (AttributeError, TypeError, ValueError):
        return None


def _completeness_label(attributes: str) -> str:
    flags = [part.strip().upper() for part in attributes.split(",") if part.strip()]
    flag = next((item for item in flags if item in {"S", "R", "P", "E"}), "")
    return {
        "S": "Standard",
        "R": "Representative",
        "P": "Provisional",
        "E": "Estimated",
    }.get(flag, "Not reported")


def _cache_is_current(path: Path, max_age_seconds: int) -> bool:
    if max_age_seconds < 0:
        return False
    try:
        return time.time() - path.stat().st_mtime <= max_age_seconds
    except OSError:
        return False


def _read_catalog_cache(path: Path) -> list[dict[str, Any]] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        return None
    return [dict(item) for item in payload]


def _write_catalog_cache(path: Path, catalog: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    try:
        temporary_path.write_text(json.dumps(catalog), encoding="utf-8")
        temporary_path.replace(path)
    except OSError:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _read_cached_precipitation_values(
    cache_dir: Path, station_id: str
) -> dict[str, float] | None:
    cache_path = cache_dir / ANNUAL_VALUE_CACHE_NAME
    with _annual_value_cache_lock:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        entry = payload.get(station_id)
        if not isinstance(entry, dict):
            return None
        values = {
            key: _number(entry.get(key)) for key in PRECIPITATION_NORMAL_RECORD_KEYS
        }
        try:
            cached_at = float(entry["cached_at"])
        except (KeyError, TypeError, ValueError):
            return None
        if (
            any(value is None for value in values.values())
            or time.time() - cached_at > ANNUAL_VALUE_CACHE_MAX_AGE_SECONDS
        ):
            return None
        return {key: float(value) for key, value in values.items() if value is not None}


def _cache_precipitation_values(
    cache_dir: Path, station_id: str, values: dict[str, float]
) -> None:
    cache_path = cache_dir / ANNUAL_VALUE_CACHE_NAME
    with _annual_value_cache_lock:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload[station_id] = {**values, "cached_at": time.time()}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_suffix(".tmp")
        try:
            temporary_path.write_text(json.dumps(payload), encoding="utf-8")
            temporary_path.replace(cache_path)
        except OSError:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _get_text(url: str) -> str:
    req = request.Request(
        url,
        headers={"Accept": "*/*", "User-Agent": USER_AGENT},
    )
    try:
        with request.urlopen(req, timeout=180) as response:
            return response.read().decode("utf-8")
    except error.HTTPError as exc:
        raise RuntimeError(f"NOAA request failed (HTTP {exc.code}).") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Could not reach NOAA: {exc.reason}") from exc


def _get_json(url: str) -> object:
    try:
        return json.loads(_get_text(url))
    except json.JSONDecodeError as exc:
        raise ValueError("NOAA returned an invalid JSON response.") from exc
