from __future__ import annotations

import json
import os
import threading
import time
from typing import Any
from urllib import parse, request

NOMINATIM_URL = os.environ.get("RWH_NOMINATIM_URL", "https://nominatim.openstreetmap.org").rstrip("/")
USER_AGENT = "RWH-Calculator/0.1.1 (+https://github.com/ianvg/rainwater-calculator-py)"
_request_lock = threading.Lock()
_last_request_time = 0.0


def reverse_geocode_osm(latitude: float, longitude: float) -> dict[str, Any]:
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Coordinates are outside the valid latitude/longitude range.")

    query = parse.urlencode(
        {
            "lat": f"{latitude:.8f}",
            "lon": f"{longitude:.8f}",
            "format": "jsonv2",
            "addressdetails": 1,
            "zoom": 18,
        }
    )
    req = request.Request(
        f"{NOMINATIM_URL}/reverse?{query}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    global _last_request_time
    with _request_lock:
        delay = 1.0 - (time.monotonic() - _last_request_time)
        if delay > 0:
            time.sleep(delay)
        with request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        _last_request_time = time.monotonic()
    if payload.get("error"):
        raise ValueError(str(payload["error"]))
    return _address_from_nominatim(payload)


def geocode_osm_address(
    address_text: str,
    country_code_alpha2: str = "",
    address_fields: dict[str, str] | None = None,
) -> dict[str, Any]:
    address_text = address_text.strip()
    if not address_text:
        raise ValueError("Enter at least one address field before searching for coordinates.")
    country_code = country_code_alpha2.strip().lower()
    attempts: list[dict[str, Any]] = []
    fields = {key: str(value).strip() for key, value in (address_fields or {}).items() if str(value).strip()}
    if fields:
        attempts.append(
            {
                key: fields[key]
                for key in ("street", "city", "state", "postalcode", "country")
                if key in fields
            }
        )
    attempts.append({"q": address_text})
    street = fields.get("street", "")
    country = fields.get("country", "")
    for parts in (
        (street, fields.get("postalcode", ""), country),
        (street, fields.get("city", ""), fields.get("state", ""), country),
    ):
        relaxed_query = ", ".join(part for part in parts if part)
        if relaxed_query and relaxed_query != address_text:
            attempts.append({"q": relaxed_query})

    for attempt in attempts:
        parameters = {**attempt, "format": "jsonv2", "addressdetails": 1, "limit": 1}
        if country_code:
            parameters["countrycodes"] = country_code
        payload = _nominatim_search(parameters)
        if payload:
            return _coordinates_from_nominatim(payload[0])
    raise ValueError("OpenStreetMap did not find coordinates matching the entered address.")


def _nominatim_search(parameters: dict[str, Any]) -> list[dict[str, Any]]:
    req = request.Request(
        f"{NOMINATIM_URL}/search?{parse.urlencode(parameters)}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    global _last_request_time
    with _request_lock:
        delay = 1.0 - (time.monotonic() - _last_request_time)
        if delay > 0:
            time.sleep(delay)
        with request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        _last_request_time = time.monotonic()
    return payload if isinstance(payload, list) else []


def _coordinates_from_nominatim(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        latitude = float(payload["lat"])
        longitude = float(payload["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("OpenStreetMap returned an invalid coordinate result.") from exc
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("OpenStreetMap returned coordinates outside the valid range.")
    return {
        "latitude": latitude,
        "longitude": longitude,
        "display_name": str(payload.get("display_name") or "").strip(),
    }


def _address_from_nominatim(payload: dict[str, Any]) -> dict[str, str]:
    address = payload.get("address") or {}
    road = _first(address, "road", "pedestrian", "residential", "path", "footway")
    house_number = str(address.get("house_number") or "").strip()
    street_address = " ".join(part for part in [house_number, road] if part)
    return {
        "street_address": street_address,
        "city": _first(address, "city", "town", "village", "municipality", "hamlet"),
        "state_or_province": _first(address, "state", "province", "region", "state_district"),
        "postal_code": str(address.get("postcode") or "").strip(),
        "country_code_alpha2": str(address.get("country_code") or "").strip().upper(),
        "display_name": str(payload.get("display_name") or "").strip(),
    }


def _first(values: dict[str, Any], *keys: str) -> str:
    return next((str(values[key]).strip() for key in keys if values.get(key)), "")
