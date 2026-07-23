from __future__ import annotations

from datetime import datetime, timezone

import rainwater_app.aviation as aviation


def test_eccc_airport_filter_uses_structured_station_type() -> None:
    stations = [
        {"sid": "airport", "station_type": "Aviation-Staffed"},
        {"sid": "climate", "station_type": "Climate-Auto"},
        {"sid": "unknown", "station_type": "N/A"},
    ]

    result = aviation.verified_airport_weather_stations(stations, "ECCC")

    assert [station["sid"] for station in result] == ["airport"]
    assert result[0]["airport_verification_source"] == "ECCC STATION_TYPE"


def test_acis_airport_filter_verifies_typed_ids_and_reuses_cache(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_fetch(identifiers: list[str]) -> list[dict]:
        calls.append(identifiers)
        return [
            {
                "icaoId": "KATL",
                "faaId": "ATL",
                "name": "Hartsfield-Jackson Atlanta International",
            }
        ]

    monkeypatch.setattr(aviation, "_fetch_airports", fake_fetch)
    stations = [
        {
            "sid": "13874",
            "identifiers": {"WBAN": ["13874"], "FAA": ["ATL"], "ICAO": ["KATL"]},
        },
        {"sid": "cooperative", "identifiers": {"COOP": ["123456"]}},
    ]
    cache_path = tmp_path / "airports.json"
    now = datetime(2026, 7, 23, tzinfo=timezone.utc)

    first = aviation.verified_airport_weather_stations(
        stations, "ACIS", cache_path=cache_path, now=now
    )
    second = aviation.verified_airport_weather_stations(
        stations, "ACIS", cache_path=cache_path, now=now
    )

    assert calls == [["KATL"]]
    assert [station["sid"] for station in first] == ["13874"]
    assert first[0]["airport_icao"] == "KATL"
    assert second == first


def test_acis_airport_filter_excludes_unverified_aviation_identifier(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(aviation, "_fetch_airports", lambda _identifiers: [])
    station = {"sid": "not-airport", "identifiers": {"FAA": ["ZZZ"]}}

    result = aviation.verified_airport_weather_stations(
        [station],
        "ACIS",
        cache_path=tmp_path / "airports.json",
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )

    assert result == []
