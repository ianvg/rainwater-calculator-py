from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import parse, request

from .app_paths import user_cache_dir

AVIATION_WEATHER_AIRPORT_URL = "https://aviationweather.gov/api/data/airport"
DEFAULT_CACHE_PATH = user_cache_dir() / "weather" / "aviation_airports.json"
POSITIVE_CACHE_AGE = timedelta(days=30)
NEGATIVE_CACHE_AGE = timedelta(days=1)
AIRPORT_REQUEST_BATCH_SIZE = 10


class AirportVerificationUnavailable(RuntimeError):
    """Raised when official airport verification cannot be completed."""


def is_eccc_aviation_station(station: dict[str, Any]) -> bool:
    return str(station.get("station_type", "")).strip().casefold().startswith("aviation-")


def acis_aviation_identifiers(station: dict[str, Any]) -> list[str]:
    identifiers = station.get("identifiers", {})
    if not isinstance(identifiers, dict):
        return []
    for identifier_type in ("ICAO", "FAA"):
        raw_values = identifiers.get(identifier_type, [])
        if not isinstance(raw_values, list):
            continue
        values = [
            str(raw_value).strip().upper()
            for raw_value in raw_values
            if str(raw_value).strip()
        ]
        if values:
            return list(dict.fromkeys(values))
    return []


def verified_airport_weather_stations(
    stations: list[dict[str, Any]],
    provider: str,
    *,
    cache_path: Path = DEFAULT_CACHE_PATH,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return stations confirmed as aviation/airport stations by official metadata."""
    if provider == "ECCC":
        return [
            {
                **station,
                "airport_verified": True,
                "airport_verification_source": "ECCC STATION_TYPE",
            }
            for station in stations
            if is_eccc_aviation_station(station)
        ]
    if provider != "ACIS":
        return []

    candidates = [station for station in stations if acis_aviation_identifiers(station)]
    if not candidates:
        return []
    reference_time = now or datetime.now(timezone.utc)
    cache = _load_cache(cache_path)
    candidate_ids = {
        identifier
        for station in candidates
        for identifier in acis_aviation_identifiers(station)
    }
    unresolved = [
        identifier
        for identifier in sorted(candidate_ids)
        if not _cache_entry_is_fresh(cache.get(identifier), reference_time)
    ]
    if unresolved:
        try:
            for start in range(0, len(unresolved), AIRPORT_REQUEST_BATCH_SIZE):
                batch = unresolved[start : start + AIRPORT_REQUEST_BATCH_SIZE]
                airport_rows = _fetch_airports(batch)
                _update_cache(cache, batch, airport_rows, reference_time)
            _save_cache(cache_path, cache)
        except Exception as exc:  # noqa: BLE001
            raise AirportVerificationUnavailable(
                "The official AviationWeather.gov airport verifier is unavailable. "
                "Try the airport-station search again later."
            ) from exc

    verified: list[dict[str, Any]] = []
    for station in candidates:
        airport = next(
            (
                cache[identifier].get("airport")
                for identifier in acis_aviation_identifiers(station)
                if _cache_entry_is_fresh(cache.get(identifier), reference_time)
                and cache[identifier].get("verified")
            ),
            None,
        )
        if not isinstance(airport, dict):
            continue
        verified.append(
            {
                **station,
                "airport_verified": True,
                "airport_verification_source": "AviationWeather.gov airport-info",
                "airport_icao": str(airport.get("icaoId") or "").strip(),
                "airport_faa": str(airport.get("faaId") or "").strip(),
                "airport_name": str(airport.get("name") or "").strip(),
            }
        )
    return verified


def _fetch_airports(identifiers: list[str]) -> list[dict[str, Any]]:
    query = parse.urlencode({"ids": ",".join(identifiers), "format": "json"})
    req = request.Request(
        f"{AVIATION_WEATHER_AIRPORT_URL}?{query}",
        headers={"Accept": "application/json", "User-Agent": "RWH-Calculator/0.1.1"},
    )
    with request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("AviationWeather.gov returned an unexpected airport response.")
    return [row for row in payload if isinstance(row, dict)]


def _airport_identifiers(airport: dict[str, Any]) -> set[str]:
    return {
        str(airport.get(field) or "").strip().upper()
        for field in ("icaoId", "iataId", "faaId")
        if str(airport.get(field) or "").strip()
    }


def _update_cache(
    cache: dict[str, dict[str, Any]],
    requested_ids: list[str],
    airport_rows: list[dict[str, Any]],
    fetched_at: datetime,
) -> None:
    matched: dict[str, dict[str, Any]] = {}
    for airport in airport_rows:
        for identifier in _airport_identifiers(airport):
            matched[identifier] = airport
    timestamp = fetched_at.astimezone(timezone.utc).isoformat(timespec="seconds")
    for identifier in requested_ids:
        airport = matched.get(identifier.upper())
        cache[identifier] = {
            "verified": airport is not None,
            "airport": airport,
            "fetched_at": timestamp,
        }


def _cache_entry_is_fresh(entry: object, now: datetime) -> bool:
    if not isinstance(entry, dict):
        return False
    try:
        fetched_at = datetime.fromisoformat(str(entry["fetched_at"]))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return False
    maximum_age = POSITIVE_CACHE_AGE if entry.get("verified") else NEGATIVE_CACHE_AGE
    return now.astimezone(timezone.utc) - fetched_at.astimezone(timezone.utc) <= maximum_age


def _load_cache(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    temporary.replace(path)
