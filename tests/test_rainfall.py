import numpy as np
import pandas as pd
import pytest

from rainwater_app.rainfall import (
    HOURLY_PRECIPITATION_COLUMNS,
    disaggregate_daily_rainfall_hyetos,
    expand_hourly_rainfall,
    has_hourly_rainfall,
    load_hourly_rainfall_csv,
    load_rainfall_csv,
    remove_hourly_rainfall,
)


def _daily_rainfall() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": pd.date_range("2025-01-01", periods=4, freq="D"),
            "Precipitation": [0.0, 0.35, 1.2, 0.08],
        }
    )


def test_hyetos_disaggregation_is_reproducible_and_conserves_daily_totals() -> None:
    rainfall = _daily_rainfall()

    first = disaggregate_daily_rainfall_hyetos(rainfall, seed=42)
    second = disaggregate_daily_rainfall_hyetos(rainfall, seed=42)

    assert has_hourly_rainfall(first)
    assert first.loc[:, HOURLY_PRECIPITATION_COLUMNS].to_numpy() == pytest.approx(
        second.loc[:, HOURLY_PRECIPITATION_COLUMNS].to_numpy()
    )
    assert first.loc[:, HOURLY_PRECIPITATION_COLUMNS].sum(axis=1).to_numpy() == pytest.approx(
        rainfall["Precipitation"].to_numpy(), abs=1e-12
    )
    assert np.all(first.loc[:, HOURLY_PRECIPITATION_COLUMNS].to_numpy() >= 0.0)
    assert np.count_nonzero(first.loc[0, list(HOURLY_PRECIPITATION_COLUMNS)].to_numpy()) == 0


def test_hyetos_disaggregation_rejects_negative_precipitation() -> None:
    rainfall = _daily_rainfall()
    rainfall.loc[0, "Precipitation"] = -0.1

    with pytest.raises(ValueError, match="cannot be negative"):
        disaggregate_daily_rainfall_hyetos(rainfall, seed=1)


def test_remove_hourly_rainfall_preserves_daily_data_and_attributes() -> None:
    rainfall = disaggregate_daily_rainfall_hyetos(_daily_rainfall(), seed=12)
    rainfall.attrs["known_missing_dates"] = ["2025-01-03"]

    daily = remove_hourly_rainfall(rainfall)

    assert not has_hourly_rainfall(daily)
    assert daily[["Date", "Precipitation"]].equals(
        rainfall[["Date", "Precipitation"]]
    )
    assert daily.attrs["known_missing_dates"] == ["2025-01-03"]


def test_expand_hourly_rainfall_uses_profiles_and_legacy_fallback() -> None:
    rainfall = _daily_rainfall().iloc[:2].copy()
    legacy = expand_hourly_rainfall(rainfall)
    generated = expand_hourly_rainfall(disaggregate_daily_rainfall_hyetos(rainfall, seed=7))

    assert len(legacy) == 48
    assert legacy.iloc[47]["Precipitation"] == pytest.approx(0.35)
    assert legacy.iloc[24:47]["Precipitation"].sum() == pytest.approx(0.0)
    assert generated.iloc[24:48]["Precipitation"].sum() == pytest.approx(0.35)
    assert generated.iloc[24:48]["Precipitation"].gt(0.0).any()


def test_csv_loader_retains_nonnumeric_precipitation_as_known_missing() -> None:
    rainfall = load_rainfall_csv(
        b"Date,Precipitation\n2025-01-01,0.2\n2025-01-02,missing\n"
    )

    assert rainfall["Precipitation"].tolist() == [0.2, 0.0]
    assert rainfall.attrs["known_missing_dates"] == ["2025-01-02"]


def test_hourly_csv_loader_detects_subdaily_timestamps_and_preserves_totals() -> None:
    rainfall = load_hourly_rainfall_csv(
        b"Date,Precipitation\n"
        b"2025-01-01 00:00,0.2\n"
        b"2025-01-01 01:00,0.3\n"
        b"2025-01-02 00:00,0.1\n"
    )

    assert rainfall.attrs["temporal_resolution"] == "hourly"
    assert rainfall["Precipitation"].tolist() == pytest.approx([0.5, 0.1])
    assert rainfall.loc[0, "HourlyPrecipitation00"] == pytest.approx(0.2)
    assert rainfall.loc[0, "HourlyPrecipitation01"] == pytest.approx(0.3)


def test_hourly_csv_loader_rejects_daily_timestamps() -> None:
    with pytest.raises(ValueError, match="subdaily timestamps"):
        load_hourly_rainfall_csv(b"Date,Precipitation\n2025-01-01,0.2\n")
