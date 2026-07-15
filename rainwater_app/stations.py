from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def bounding_box(latitude: float, longitude: float, radius_km: float) -> tuple[float, float, float, float]:
    latitude_delta = radius_km / 111.32
    longitude_scale = max(math.cos(math.radians(latitude)), 0.01)
    longitude_delta = radius_km / (111.32 * longitude_scale)
    return (
        max(longitude - longitude_delta, -180.0),
        max(latitude - latitude_delta, -90.0),
        min(longitude + longitude_delta, 180.0),
        min(latitude + latitude_delta, 90.0),
    )


def station_distance_km(station: dict, latitude: float, longitude: float) -> float | None:
    try:
        station_latitude = float(station["latitude"])
        station_longitude = float(station["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not -90 <= station_latitude <= 90 or not -180 <= station_longitude <= 180:
        return None
    lat1, lat2 = math.radians(latitude), math.radians(station_latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(station_longitude - longitude)
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(math.sqrt(haversine), 1.0))


def nearest_stations(stations: list[dict], latitude: float, longitude: float, limit: int = 10) -> list[dict]:
    ranked: list[dict] = []
    for station in stations:
        distance = station_distance_km(station, latitude, longitude)
        if distance is None:
            continue
        item = dict(station)
        item["distance_km"] = distance
        ranked.append(item)
    return sorted(ranked, key=lambda station: (station["distance_km"], station["name"].casefold()))[:limit]
