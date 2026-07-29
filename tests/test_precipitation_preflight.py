from datetime import date

import pandas as pd
import pytest

from rainwater_app.precipitation_preflight import (
    assess_station_coverage,
    compare_station_coverage,
)


def test_assess_station_coverage_counts_requested_valid_days_and_known_missing() -> None:
    def loader(_station_id, _start, _end, _field):
        result = pd.DataFrame(
            {
                "Date": ["2024-01-01", "2024-01-02", "2024-01-04", "2025-01-01"],
                "Precipitation": [0.1, 0.0, 0.2, 0.3],
            }
        )
        result.attrs["known_missing_dates"] = ["2024-01-02"]
        return result

    coverage = assess_station_coverage(
        {"sid": "A", "name": "Alpha", "provider": "ACIS"},
        date(2024, 1, 1),
        date(2024, 1, 4),
        "TOTAL_PRECIPITATION",
        loader,
    )

    assert coverage.expected_days == 4
    assert coverage.observed_days == 2
    assert coverage.missing_days == 2
    assert coverage.completeness_percent == pytest.approx(50.0)
    assert coverage.record_start == date(2024, 1, 1)
    assert coverage.record_end == date(2025, 1, 1)


def test_compare_station_coverage_ranks_completeness_and_retains_failures() -> None:
    def loader(station_id, start, _end, _field):
        if station_id == "failed":
            raise RuntimeError("provider unavailable")
        days = 3 if station_id == "complete" else 2
        return pd.DataFrame(
            {
                "Date": pd.date_range(start, periods=days, freq="D"),
                "Precipitation": [0.0] * days,
            }
        )

    stations = [
        {"sid": "partial", "name": "Partial", "provider": "ACIS"},
        {"sid": "failed", "name": "Failed", "provider": "ACIS"},
        {"sid": "complete", "name": "Complete", "provider": "ACIS"},
    ]
    results = compare_station_coverage(
        stations,
        date(2025, 1, 1),
        date(2025, 1, 3),
        loaders={"ACIS": loader},
        max_workers=2,
    )

    assert [result.station_id for result in results] == ["complete", "partial", "failed"]
    assert results[0].completeness_percent == pytest.approx(100.0)
    assert results[-1].error == "provider unavailable"


def test_assess_station_coverage_rejects_reversed_period() -> None:
    with pytest.raises(ValueError, match="end date"):
        assess_station_coverage(
            {"sid": "A", "name": "Alpha", "provider": "ACIS"},
            date(2025, 1, 2),
            date(2025, 1, 1),
            "TOTAL_PRECIPITATION",
            lambda *_args: pd.DataFrame(),
        )
