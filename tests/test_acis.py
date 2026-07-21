import json
from datetime import date

import pytest

from rainwater_app.acis import fetch_daily_station_data, fetch_station_by_id


@pytest.fixture
def acis_cache(tmp_path):
    cache_file = tmp_path / "acis_test_20200101_20200102.json"
    cache_file.write_text(
        json.dumps(
            {
                "data": [
                    ["2020-01-01", "40", "30", "0.25", "0"],
                    ["2020-01-02", "34", "25", "0.40", "2.0"],
                ]
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_acis_total_precipitation_keeps_snowfall_day_precipitation(acis_cache) -> None:
    data = fetch_daily_station_data(
        "test", date(2020, 1, 1), date(2020, 1, 2), "TOTAL_PRECIPITATION", acis_cache
    )

    assert data["Precipitation"].tolist() == [0.25, 0.4]
    assert data.attrs["rain_only_excluded_days"] == 0


def test_acis_rain_only_excludes_precipitation_on_snowfall_days(acis_cache) -> None:
    data = fetch_daily_station_data(
        "test", date(2020, 1, 1), date(2020, 1, 2), "TOTAL_RAIN", acis_cache
    )

    assert data["Precipitation"].tolist() == [0.25, 0.0]
    assert data.attrs["rain_only_excluded_days"] == 1


def test_acis_rejects_unknown_precipitation_basis(acis_cache) -> None:
    with pytest.raises(ValueError, match="Unsupported ACIS precipitation basis"):
        fetch_daily_station_data("test", date(2020, 1, 1), date(2020, 1, 2), "OTHER", acis_cache)


def test_acis_preserves_missing_precipitation_dates_for_quality_scoring(tmp_path) -> None:
    cache_file = tmp_path / "acis_missing_20200101_20200102.json"
    cache_file.write_text(
        json.dumps(
            {
                "data": [
                    ["2020-01-01", "40", "30", "M", "0"],
                    ["2020-01-02", "41", "31", "0.1", "0"],
                ]
            }
        ),
        encoding="utf-8",
    )

    data = fetch_daily_station_data(
        "missing", date(2020, 1, 1), date(2020, 1, 2), cache_dir=tmp_path
    )

    assert data.attrs["known_missing_dates"] == ["2020-01-01"]


def test_fetch_station_by_id_uses_stnmeta_sids_and_returns_coordinates(monkeypatch) -> None:
    captured = {}

    def fake_post(_url, payload):
        captured.update(payload)
        return {
            "meta": [{
                "name": "ATHENS BEN EPPS AP", "state": "GA",
                "sids": ["13873 1"], "ll": [-83.32736, 33.94773], "elev": 784,
            }]
        }

    monkeypatch.setattr("rainwater_app.acis._post_json", fake_post)
    station = fetch_station_by_id("13873")

    assert captured["sids"] == "13873"
    assert station is not None
    assert station["latitude"] == 33.94773
    assert station["longitude"] == -83.32736
