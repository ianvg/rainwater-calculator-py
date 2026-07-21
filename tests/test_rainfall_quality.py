from __future__ import annotations

import pandas as pd
import pytest

from rainwater_app.rainfall_quality import (
    assess_rainfall_record,
    rainfall_data_type_label,
)


def test_quality_scores_full_calendar_coverage_and_provider_missing_dates() -> None:
    rainfall = pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", "2024-12-31", freq="D"),
            "Precipitation": 0.0,
        }
    )

    quality = assess_rainfall_record(
        rainfall,
        known_missing_dates=["2024-03-04", "2024-03-05"],
    )

    assert quality.expected_days == 366
    assert quality.observed_days == 364
    assert quality.missing_days == 2
    assert quality.completeness_percent == pytest.approx(364 / 366 * 100.0)
    assert quality.completeness_rating == "Good"
    assert quality.partial_years == (2024,)
    assert quality.missing_periods[0].to_dict() == {
        "start": "2024-03-04",
        "end": "2024-03-05",
        "days": 2,
    }


def test_quality_exposes_partial_boundary_years_and_yearly_summaries() -> None:
    rainfall = pd.DataFrame(
        {
            "Date": pd.date_range("2023-07-01", "2024-06-30", freq="D"),
            "Precipitation": 0.1,
        }
    )

    quality = assess_rainfall_record(rainfall)

    assert quality.partial_years == (2023, 2024)
    assert quality.missing_periods[0].start == "2023-01-01"
    assert quality.missing_periods[-1].end == "2024-12-31"
    assert quality.yearly_summaries[0].observed_days == 184
    assert quality.yearly_summaries[1].observed_days == 182
    assert all(summary.partial_year for summary in quality.yearly_summaries)


def test_quality_builds_rainfall_events_using_antecedent_dry_threshold() -> None:
    rainfall = pd.DataFrame(
        {
            "Date": pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-06"]
            ),
            "Precipitation": [0.2, 0.1, 0.0, 0.4, 0.5],
        }
    )

    quality = assess_rainfall_record(rainfall, antecedent_dry_days=1.0)

    assert quality.event_count == 3
    assert quality.event_summaries[0].start == "2025-01-01"
    assert quality.event_summaries[0].end == "2025-01-02"
    assert quality.event_summaries[0].precipitation == pytest.approx(0.3)
    assert quality.event_summaries[1].precipitation == pytest.approx(0.4)
    assert quality.event_summaries[2].precipitation == pytest.approx(0.5)


def test_data_type_labels_are_explicit_and_unknown_values_are_unclassified() -> None:
    assert rainfall_data_type_label("observed") == "Observed station data"
    assert rainfall_data_type_label("synthetic") == "Synthetic rainfall data"
    assert rainfall_data_type_label("reanalysis") == "Gridded reanalysis data"
    assert rainfall_data_type_label("other") == "Unclassified user-supplied data"


def test_invalid_and_duplicate_rows_are_disclosed_and_not_counted_as_observed() -> None:
    rainfall = pd.DataFrame(
        {
            "Date": ["2025-01-01", "2025-01-01", "2025-01-02", "2025-01-03"],
            "Precipitation": [0.1, 0.2, -1.0, float("nan")],
        }
    )

    quality = assess_rainfall_record(rainfall)

    assert quality.duplicate_dates == 1
    assert quality.invalid_precipitation_rows == 2
    assert quality.observed_days == 1
