from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib import parse, request

import pandas as pd

from .units import MM_PER_INCH

ECCC_API_ROOT = "https://api.weather.gc.ca/collections"
ECCC_STATIONS_URL = f"{ECCC_API_ROOT}/climate-stations/items"
ECCC_DAILY_URL = f"{ECCC_API_ROOT}/climate-daily/items"
DEFAULT_CACHE_DIR = Path(".weather_cache")
PRECIPITATION_FIELDS = {"TOTAL_PRECIPITATION", "TOTAL_RAIN"}


def fetch_canadian_station_options(province: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
    province = province.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", province):
        raise ValueError("Province or territory must use a two-letter abbreviation.")

    features = _get_feature_pages(
        ECCC_STATIONS_URL,
        {"f": "json", "limit": 1000, "PROV_STATE_TERR_CODE": province},
    )
    return _station_options_from_features(features, start_date, end_date, province)


def fetch_canadian_station_options_bbox(
    west: float, south: float, east: float, north: float, start_date: date, end_date: date
) -> list[dict[str, Any]]:
    features = _get_feature_pages(
        ECCC_STATIONS_URL,
        {"f": "json", "limit": 1000, "bbox": f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}"},
    )
    return _station_options_from_features(features, start_date, end_date)


def fetch_canadian_station_by_id(station_id: str) -> dict[str, Any] | None:
    """Return one ECCC climate station, including coordinates."""
    features = _get_feature_pages(
        ECCC_STATIONS_URL,
        {"f": "json", "limit": 10, "CLIMATE_IDENTIFIER": station_id.strip()},
    )
    for feature in features:
        properties = feature.get("properties", {})
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        identifier = str(properties.get("CLIMATE_IDENTIFIER") or "").strip()
        if identifier != station_id.strip():
            continue
        return {
            "sid": identifier,
            "name": str(properties.get("STATION_NAME") or "Unnamed station").strip(),
            "state": str(properties.get("PROV_STATE_TERR_CODE") or "").strip(),
            "longitude": _coordinate(coordinates, 0),
            "latitude": _coordinate(coordinates, 1),
            "provider": "ECCC",
        }
    return None


def _station_options_from_features(
    features: list[dict[str, Any]], start_date: date, end_date: date, default_province: str = ""
) -> list[dict[str, Any]]:
    stations: list[dict[str, Any]] = []
    for feature in features:
        properties = feature.get("properties", {})
        station_id = str(properties.get("CLIMATE_IDENTIFIER") or "").strip()
        first_date = _parse_date(properties.get("DLY_FIRST_DATE"))
        last_date = _parse_date(properties.get("DLY_LAST_DATE"))
        if not station_id or first_date is None or last_date is None:
            continue
        if first_date > end_date or last_date < start_date:
            continue
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        stations.append(
            {
                "sid": station_id,
                "name": str(properties.get("STATION_NAME") or "Unnamed station").strip(),
                "state": str(properties.get("PROV_STATE_TERR_CODE") or default_province).strip(),
                "longitude": _coordinate(coordinates, 0),
                "latitude": _coordinate(coordinates, 1),
                "first_date": first_date.isoformat(),
                "last_date": last_date.isoformat(),
                "provider": "ECCC",
            }
        )
    return sorted(stations, key=lambda station: (station["name"].casefold(), station["sid"]))


def fetch_canadian_daily_station_data(
    station_id: str,
    start_date: date,
    end_date: date,
    precipitation_field: str = "TOTAL_PRECIPITATION",
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    field = precipitation_field.strip().upper()
    if field not in PRECIPITATION_FIELDS:
        raise ValueError("Canadian precipitation field must be TOTAL_PRECIPITATION or TOTAL_RAIN.")

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / (
        f"eccc_{_safe_cache_part(station_id)}_{start_date:%Y%m%d}_{end_date:%Y%m%d}_{field.lower()}.json"
    )
    if cache_file.exists():
        features = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        features = _get_feature_pages(
            ECCC_DAILY_URL,
            {
                "f": "json",
                "limit": 1000,
                "CLIMATE_IDENTIFIER": station_id,
                "datetime": f"{start_date.isoformat()}/{end_date.isoformat()}",
            },
        )
        cache_file.write_text(json.dumps(features), encoding="utf-8")

    return _daily_features_to_dataframe(features, start_date, end_date, field)


def _daily_features_to_dataframe(
    features: list[dict[str, Any]],
    start_date: date,
    end_date: date,
    precipitation_field: str,
) -> pd.DataFrame:
    rows = []
    for feature in features:
        properties = feature.get("properties", {})
        observation_date = pd.to_datetime(properties.get("LOCAL_DATE"), errors="coerce")
        if pd.isna(observation_date):
            continue
        rows.append({"Date": observation_date.normalize(), "PrecipitationMM": properties.get(precipitation_field)})

    if not rows:
        raise ValueError("ECCC returned no valid daily observations for this station and date range.")

    data = pd.DataFrame(rows).drop_duplicates(subset=["Date"], keep="last").set_index("Date").sort_index()
    data["PrecipitationMM"] = pd.to_numeric(data["PrecipitationMM"], errors="coerce")
    calendar = pd.date_range(start_date, end_date, freq="D")
    data = data.reindex(calendar)
    missing_days = int(data["PrecipitationMM"].isna().sum())
    data["PrecipitationMM"] = data["PrecipitationMM"].fillna(0.0).clip(lower=0.0)
    result = pd.DataFrame(
        {
            "Date": calendar,
            "Precipitation": data["PrecipitationMM"].to_numpy() / MM_PER_INCH,
        }
    )
    result.attrs["missing_days"] = missing_days
    return result


def _get_feature_pages(url: str, params: dict[str, object], max_pages: int = 250) -> list[dict[str, Any]]:
    next_url: str | None = f"{url}?{parse.urlencode(params)}"
    features: list[dict[str, Any]] = []
    pages = 0
    while next_url:
        pages += 1
        if pages > max_pages:
            raise RuntimeError("ECCC response exceeded the pagination safety limit.")
        payload = _get_json(next_url)
        page_features = payload.get("features", [])
        if not page_features:
            break
        features.extend(page_features)
        next_url = next(
            (str(link.get("href")) for link in payload.get("links", []) if link.get("rel") == "next" and link.get("href")),
            None,
        )
    return features


def _get_json(url: str) -> dict[str, Any]:
    req = request.Request(url, headers={"Accept": "application/geo+json", "User-Agent": "RWH-Calculator/0.1.1"})
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_date(value: object) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def _coordinate(coordinates: list[object], index: int) -> float | None:
    try:
        return float(coordinates[index])
    except (IndexError, TypeError, ValueError):
        return None


def _safe_cache_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
