from datetime import date

import pytest

from rainwater_app.eccc import _daily_features_to_dataframe
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


def test_daily_features_reject_empty_response() -> None:
    with pytest.raises(ValueError, match="no valid daily observations"):
        _daily_features_to_dataframe([], date(2025, 1, 1), date(2025, 1, 2), "TOTAL_PRECIPITATION")
