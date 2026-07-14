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
