from __future__ import annotations

from io import BytesIO
from dataclasses import dataclass

import numpy as np
import pandas as pd


HOURLY_PRECIPITATION_COLUMNS = tuple(
    f"HourlyPrecipitation{hour:02d}" for hour in range(24)
)


@dataclass(frozen=True)
class HyetosParameters:
    """Parameters for Hyetos-style Bartlett-Lewis rainfall disaggregation.

    The defaults are intentionally general-purpose. Projects with observed
    hourly data should calibrate these values for their climate before using
    the synthetic series for design decisions.
    """

    mean_cells_per_storm: float = 3.5
    mean_cell_delay_hours: float = 1.75
    mean_cell_duration_hours: float = 2.25
    cell_intensity_shape: float = 1.35
    repetitions: int = 24


def has_hourly_rainfall(rainfall_df: pd.DataFrame) -> bool:
    """Return whether all 24 synthetic hourly precipitation columns exist."""
    return all(column in rainfall_df.columns for column in HOURLY_PRECIPITATION_COLUMNS)


def _rectangular_pulse_profile(
    rng: np.random.Generator, parameters: HyetosParameters
) -> np.ndarray:
    """Generate one 24-hour Bartlett-Lewis rectangular-pulse profile."""
    profile = np.zeros(24, dtype=np.float64)
    storm_origin = rng.uniform(-3.0, 21.0)
    cell_count = max(1, 1 + int(rng.poisson(max(parameters.mean_cells_per_storm - 1.0, 0.0))))
    for cell_index in range(cell_count):
        delay = 0.0 if cell_index == 0 else rng.exponential(parameters.mean_cell_delay_hours)
        start = storm_origin + delay
        duration = max(float(rng.exponential(parameters.mean_cell_duration_hours)), 0.05)
        end = start + duration
        intensity = float(rng.gamma(parameters.cell_intensity_shape, 1.0))
        first_hour = max(int(np.floor(start)), 0)
        last_hour = min(int(np.ceil(end)), 24)
        for hour in range(first_hour, last_hour):
            overlap = max(min(end, hour + 1.0) - max(start, float(hour)), 0.0)
            profile[hour] += intensity * overlap
    return profile


def disaggregate_daily_rainfall_hyetos(
    rainfall_df: pd.DataFrame,
    *,
    seed: int | None = None,
    parameters: HyetosParameters | None = None,
) -> pd.DataFrame:
    """Attach a reproducible Hyetos-style hourly profile to each daily total.

    Candidate hyetographs are generated with Bartlett-Lewis rectangular
    pulses. A repetition step selects a candidate with a plausible number of
    wet hours for the day's depth, then the Hyetos adjusting step scales its
    24 hourly values to reproduce the observed daily total exactly.
    """
    required = {"Date", "Precipitation"}
    if not required.issubset(rainfall_df.columns):
        raise ValueError("Rainfall data must contain 'Date' and 'Precipitation' columns.")
    params = parameters or HyetosParameters()
    if params.mean_cells_per_storm <= 0.0:
        raise ValueError("Mean cells per storm must be greater than zero.")
    if params.mean_cell_delay_hours <= 0.0 or params.mean_cell_duration_hours <= 0.0:
        raise ValueError("Cell delay and duration must be greater than zero.")
    if params.cell_intensity_shape <= 0.0 or params.repetitions < 1:
        raise ValueError("Cell intensity shape and repetitions must be positive.")

    result = rainfall_df.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result["Precipitation"] = pd.to_numeric(
        result["Precipitation"], errors="coerce"
    ).fillna(0.0)
    if result["Date"].isna().any():
        raise ValueError("Rainfall data contains invalid dates.")
    if (result["Precipitation"] < 0.0).any():
        raise ValueError("Rainfall precipitation cannot be negative.")

    rng = np.random.default_rng(seed)
    positive = result.loc[result["Precipitation"] > 0.0, "Precipitation"]
    typical_depth = max(float(positive.median()) if not positive.empty else 1.0, 1e-12)
    hourly_rows: list[np.ndarray] = []
    for daily_depth in result["Precipitation"].to_numpy(dtype=float):
        if daily_depth <= 0.0:
            hourly_rows.append(np.zeros(24, dtype=np.float64))
            continue
        target_wet_hours = float(np.clip(2.0 + 3.0 * np.log1p(daily_depth / typical_depth), 1.0, 18.0))
        best_profile: np.ndarray | None = None
        best_score = float("inf")
        for _ in range(params.repetitions):
            candidate = _rectangular_pulse_profile(rng, params)
            total = float(candidate.sum())
            if total <= 0.0:
                continue
            wet_hours = int(np.count_nonzero(candidate > total * 1e-8))
            score = abs(wet_hours - target_wet_hours)
            if score < best_score:
                best_profile = candidate
                best_score = score
        if best_profile is None:
            best_profile = np.zeros(24, dtype=np.float64)
            best_profile[int(rng.integers(0, 24))] = 1.0
        adjusted = best_profile * (daily_depth / float(best_profile.sum()))
        # Put floating-point residual in the largest hour for exact conservation.
        adjusted[int(np.argmax(adjusted))] += daily_depth - float(adjusted.sum())
        hourly_rows.append(adjusted)

    hourly = np.vstack(hourly_rows) if hourly_rows else np.empty((0, 24))
    for hour, column in enumerate(HOURLY_PRECIPITATION_COLUMNS):
        result[column] = hourly[:, hour]
    return result


def expand_hourly_rainfall(
    rainfall_df: pd.DataFrame, *, use_synthetic: bool = True
) -> pd.DataFrame:
    """Return hourly Date/Precipitation rows, preserving the legacy fallback."""
    daily = rainfall_df.copy()
    daily["Date"] = pd.to_datetime(daily["Date"], errors="coerce")
    daily["Precipitation"] = pd.to_numeric(
        daily["Precipitation"], errors="coerce"
    ).fillna(0.0)
    daily = daily.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    values = np.zeros((len(daily), 24), dtype=np.float64)
    if use_synthetic and has_hourly_rainfall(daily):
        values = daily.loc[:, HOURLY_PRECIPITATION_COLUMNS].apply(
            pd.to_numeric, errors="coerce"
        ).fillna(0.0).to_numpy(dtype=np.float64)
        values = np.maximum(values, 0.0)
    else:
        values[:, 23] = np.maximum(daily["Precipitation"].to_numpy(dtype=float), 0.0)
    dates = [
        pd.Timestamp(date).normalize() + pd.Timedelta(hours=hour)
        for date in daily["Date"] for hour in range(24)
    ]
    return pd.DataFrame({"Date": dates, "Precipitation": values.reshape(-1)})


def load_rainfall_csv(file_bytes: bytes) -> pd.DataFrame:
    """Load rainfall CSV containing Date and Precipitation columns."""
    if not file_bytes:
        raise ValueError("Rainfall file is empty.")

    df = pd.read_csv(BytesIO(file_bytes))

    normalized = {c.lower().strip(): c for c in df.columns}
    required = {"date", "precipitation"}
    if not required.issubset(set(normalized.keys())):
        raise ValueError("CSV must include Date and Precipitation columns.")

    result = df[[normalized["date"], normalized["precipitation"]]].copy()
    result.columns = ["Date", "Precipitation"]
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result["Precipitation"] = pd.to_numeric(result["Precipitation"], errors="coerce")
    missing_dates = result.loc[
        result["Date"].notna() & result["Precipitation"].isna(), "Date"
    ].dt.normalize()
    result = result.dropna(subset=["Date"]).fillna({"Precipitation": 0.0})
    result = result.sort_values("Date").reset_index(drop=True)

    if result.empty:
        raise ValueError("No valid rows found after parsing Date/Precipitation.")

    result.attrs["known_missing_dates"] = [
        value.date().isoformat() for value in missing_dates
    ]
    return result
