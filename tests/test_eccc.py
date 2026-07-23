from datetime import date

import pytest

from rainwater_app.eccc import _daily_features_to_dataframe, _station_options_from_features
from rainwater_app.units import MM_PER_INCH


def test_daily_features_select_field_complete_calendar_and_convert_mm() -> None:
    features = [
        {
            "properties": {
                "LOCAL_DATE": "2025-01-01 00:00:00",
                "TOTAL_PRECIPITATION": 25.4,
                "TOTAL_RAIN": 10.0,
            }
        },
        {
            "properties": {
                "LOCAL_DATE": "2025-01-03 00:00:00",
                "TOTAL_PRECIPITATION": 12.7,
                "TOTAL_RAIN": None,
            }
        },
    ]

    result = _daily_features_to_dataframe(features, date(2025, 1, 1), date(2025, 1, 3), "TOTAL_RAIN")

    assert result["Precipitation"].tolist() == pytest.approx([10.0 / MM_PER_INCH, 0.0, 0.0])
    assert result.attrs["missing_days"] == 2
    assert result.attrs["known_missing_dates"] == ["2025-01-02", "2025-01-03"]


def test_daily_features_reject_empty_response() -> None:
    with pytest.raises(ValueError, match="no valid daily observations"):
        _daily_features_to_dataframe([], date(2025, 1, 1), date(2025, 1, 2), "TOTAL_PRECIPITATION")


def test_station_options_retain_authoritative_aviation_metadata() -> None:
    features = [
        {
            "geometry": {"coordinates": [-123.11, 49.19]},
            "properties": {
                "CLIMATE_IDENTIFIER": "1108395",
                "STATION_NAME": "VANCOUVER INTL A",
                "PROV_STATE_TERR_CODE": "BC",
                "DLY_FIRST_DATE": "1990-01-01",
                "DLY_LAST_DATE": "2026-01-01",
                "STATION_TYPE": "Aviation-Staffed",
                "TC_IDENTIFIER": "YVR",
                "WMO_IDENTIFIER": "71892",
                "ENG_STN_OPERATOR_NAME": "NAV Canada",
            },
        }
    ]

    stations = _station_options_from_features(
        features, date(2000, 1, 1), date(2025, 12, 31)
    )

    assert stations[0]["station_type"] == "Aviation-Staffed"
    assert stations[0]["tc_identifier"] == "YVR"
    assert stations[0]["wmo_identifier"] == "71892"
    assert stations[0]["station_operator"] == "NAV Canada"
