from __future__ import annotations

import queue
from datetime import date
from types import SimpleNamespace

import tkinter_app
from tkinter_app import RainwaterTkApp


def test_airport_lookup_worker_returns_five_verified_stations_ranked_by_distance(
    monkeypatch,
) -> None:
    stations = [
        {
            "sid": str(index),
            "name": f"Airport {index}",
            "latitude": 40.0 + index / 100.0,
            "longitude": -75.0,
            "provider": "ACIS",
            "identifiers": {"ICAO": [f"K{index:03d}"]},
        }
        for index in range(7)
    ]
    monkeypatch.setattr(
        tkinter_app, "fetch_station_options_bbox", lambda *_args: stations
    )
    monkeypatch.setattr(
        tkinter_app,
        "verified_airport_weather_stations",
        lambda values, _provider, **_kwargs: [
            {**station, "airport_verified": True} for station in values
        ],
    )
    app = SimpleNamespace(
        station_lookup_queue=queue.Queue(),
        execution_log=SimpleNamespace(
            diagnostic=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
        ),
    )

    RainwaterTkApp._nearest_station_lookup_worker(
        app,
        "ACIS",
        40.0,
        -75.0,
        date(1996, 1, 1),
        date(2025, 12, 31),
        True,
    )

    result, provider, payload = app.station_lookup_queue.get_nowait()
    assert result == "success"
    assert provider == "ACIS"
    assert len(payload) == 5
    assert [station["sid"] for station in payload] == ["0", "1", "2", "3", "4"]


def test_airport_station_label_displays_verified_identifier() -> None:
    label = RainwaterTkApp._station_label(
        {
            "name": "Airport Station",
            "sid": "12345",
            "state": "PA",
            "provider": "ACIS",
            "airport_verified": True,
            "airport_icao": "KPHL",
        }
    )

    assert label == "Airport Station - 12345 [Airport KPHL] in Pennsylvania"
