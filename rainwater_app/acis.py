from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib import request

import pandas as pd

ACIS_STATION_META_URL = "https://data.rcc-acis.org/StnMeta"
ACIS_STATION_DATA_URL = "https://data.rcc-acis.org/StnData"
DEFAULT_CACHE_DIR = Path(".weather_cache")


def default_complete_calendar_range(years: int = 30, today: date | None = None) -> tuple[date, date]:
    if years < 30:
        raise ValueError("Historical weather imports require at least 30 years.")

    reference = today or date.today()
    end_year = reference.year - 1
    start_year = end_year - years + 1
    return date(start_year, 1, 1), date(end_year, 12, 31)


def fetch_station_options(state: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
    state = state.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", state):
        raise ValueError("State must be a two-letter USPS abbreviation.")

    payload = {
        "state": state,
        "sdate": start_date.isoformat(),
        "edate": end_date.isoformat(),
        "meta": ["name", "sids", "state", "ll", "elev"],
    }
    response = _post_json(ACIS_STATION_META_URL, payload)

    return _station_options_from_meta(response, state)


def fetch_station_options_bbox(
    west: float, south: float, east: float, north: float, start_date: date, end_date: date
) -> list[dict[str, Any]]:
    payload = {
        "bbox": f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}",
        "sdate": start_date.isoformat(),
        "edate": end_date.isoformat(),
        "meta": ["name", "sids", "state", "ll", "elev"],
    }
    return _station_options_from_meta(_post_json(ACIS_STATION_META_URL, payload))


def _station_options_from_meta(response: dict[str, Any], default_state: str = "") -> list[dict[str, Any]]:
    stations: list[dict[str, Any]] = []
    for item in response.get("meta", []):
        sid = _primary_station_id(item.get("sids", []))
        if not sid:
            continue
        stations.append(
            {
                "sid": sid,
                "name": str(item.get("name", "Unnamed station")),
                "state": str(item.get("state", default_state)),
                "longitude": _safe_coordinate(item, 0),
                "latitude": _safe_coordinate(item, 1),
                "elevation_ft": item.get("elev"),
                "provider": "ACIS",
            }
        )

    return stations


def fetch_daily_station_data(
    station_id: str,
    start_date: date,
    end_date: date,
    precipitation_basis: str = "TOTAL_PRECIPITATION",
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    if precipitation_basis not in {"TOTAL_PRECIPITATION", "TOTAL_RAIN"}:
        raise ValueError(f"Unsupported ACIS precipitation basis: {precipitation_basis}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"acis_{_safe_cache_part(station_id)}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.json"

    if cache_file.exists():
        response = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        payload = {
            "sid": station_id,
            "sdate": start_date.isoformat(),
            "edate": end_date.isoformat(),
            "elems": [
                {"name": "maxt"},
                {"name": "mint"},
                {"name": "pcpn"},
                {"name": "snow"},
            ],
        }
        response = _post_json(ACIS_STATION_DATA_URL, payload)
        cache_file.write_text(json.dumps(response, indent=2), encoding="utf-8")

    rows = []
    excluded_snowfall_days = 0
    for row in response.get("data", []):
        if len(row) < 5:
            continue
        precipitation = _parse_acis_number(row[3])
        snowfall = _parse_acis_number(row[4])
        if precipitation_basis == "TOTAL_RAIN" and snowfall > 0:
            precipitation = 0.0
            excluded_snowfall_days += 1
        rows.append(
            {
                "Date": pd.to_datetime(row[0], errors="coerce"),
                "MaxTemperature": _parse_acis_number(row[1]),
                "MinTemperature": _parse_acis_number(row[2]),
                "Precipitation": precipitation,
                "Snowfall": snowfall,
            }
        )

    data = pd.DataFrame(rows).dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    if data.empty:
        raise ValueError("ACIS returned no valid daily weather rows for this station and date range.")

    data.attrs["rain_only_excluded_days"] = excluded_snowfall_days

    return data


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _primary_station_id(sids: list[str]) -> str:
    for sid in sids:
        value = str(sid).split()[0].strip()
        if value:
            return value
    return ""


def _safe_coordinate(item: dict[str, Any], index: int) -> float | None:
    try:
        return float(item["ll"][index])
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def _parse_acis_number(value: Any) -> float:
    text = str(value).strip()
    if not text or text.upper() in {"M", "S"}:
        return 0.0
    if text.upper().startswith("T"):
        return 0.0

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else 0.0


def _safe_cache_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
