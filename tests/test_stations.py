import pytest

from rainwater_app.stations import (
    bounding_box,
    filter_stations,
    nearest_stations,
    station_distance_km,
)


def test_station_filter_matches_any_semicolon_separated_name_or_id() -> None:
    stations = [
        {"name": "CITY AIRPORT", "sid": "AIR001"},
        {"name": "COUNTY AP", "sid": "AP002"},
        {"name": "DOWNTOWN", "sid": "CITY003"},
    ]

    assert filter_stations(stations, " AIRPORT; AP ") == stations[:2]
    assert filter_stations(stations, "city003") == stations[2:]


def test_station_filter_ignores_empty_terms_and_preserves_unfiltered_results() -> None:
    stations = [{"name": "CITY AIRPORT", "sid": "AIR001"}]

    assert filter_stations(stations, " ; ") is stations


def test_station_distance_and_ranking_use_great_circle_distance() -> None:
    origin = (33.8855057, -83.3756241)
    stations = [
        {"name": "Far", "latitude": 34.5, "longitude": -84.0},
        {"name": "Nearest", "latitude": 33.89, "longitude": -83.38},
        {"name": "Middle", "latitude": 34.0, "longitude": -83.5},
    ]

    ranked = nearest_stations(stations, *origin, limit=2)

    assert [station["name"] for station in ranked] == ["Nearest", "Middle"]
    assert ranked[0]["distance_km"] < ranked[1]["distance_km"]
    assert station_distance_km(stations[1], *origin) == pytest.approx(ranked[0]["distance_km"])


def test_bounding_box_contains_requested_origin() -> None:
    west, south, east, north = bounding_box(43.65, -79.38, 50.0)

    assert west < -79.38 < east
    assert south < 43.65 < north


def test_nearest_stations_ignore_invalid_coordinates_and_limit_results() -> None:
    stations = [
        {"name": f"Station {index}", "latitude": 40.0 + index / 100, "longitude": -75.0}
        for index in range(12)
    ]
    stations.append({"name": "Invalid", "latitude": None, "longitude": -75.0})

    assert len(nearest_stations(stations, 40.0, -75.0)) == 10
