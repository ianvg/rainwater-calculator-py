from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable

import pandas as pd


RAINFALL_DATA_TYPE_LABELS = {
    "unclassified": "Unclassified user-supplied data",
    "observed": "Observed station data",
    "synthetic": "Synthetic rainfall data",
    "interpolated": "Interpolated rainfall data",
    "reanalysis": "Gridded reanalysis data",
}


@dataclass(frozen=True)
class MissingPeriod:
    start: str
    end: str
    days: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class YearlyRainfallSummary:
    year: int
    expected_days: int
    observed_days: int
    missing_days: int
    completeness_percent: float
    precipitation: float
    wet_days: int
    partial_year: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RainfallEventSummary:
    event_number: int
    start: str
    end: str
    duration_days: int
    wet_days: int
    precipitation: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RainfallQualityAssessment:
    record_start: str | None
    record_end: str | None
    expected_days: int
    observed_days: int
    missing_days: int
    duplicate_dates: int
    invalid_precipitation_rows: int
    completeness_percent: float
    completeness_rating: str
    partial_years: tuple[int, ...]
    missing_periods: tuple[MissingPeriod, ...]
    yearly_summaries: tuple[YearlyRainfallSummary, ...]
    event_summaries: tuple[RainfallEventSummary, ...]

    @property
    def event_count(self) -> int:
        return len(self.event_summaries)

    def to_dict(self) -> dict[str, object]:
        return {
            "record_start": self.record_start,
            "record_end": self.record_end,
            "expected_days": self.expected_days,
            "observed_days": self.observed_days,
            "missing_days": self.missing_days,
            "duplicate_dates": self.duplicate_dates,
            "invalid_precipitation_rows": self.invalid_precipitation_rows,
            "completeness_percent": self.completeness_percent,
            "completeness_rating": self.completeness_rating,
            "partial_years": list(self.partial_years),
            "missing_periods": [period.to_dict() for period in self.missing_periods],
            "yearly_summaries": [summary.to_dict() for summary in self.yearly_summaries],
            "event_summaries": [summary.to_dict() for summary in self.event_summaries],
        }


def rainfall_data_type_label(value: object) -> str:
    normalized = str(value or "unclassified").strip().casefold()
    return RAINFALL_DATA_TYPE_LABELS.get(
        normalized, RAINFALL_DATA_TYPE_LABELS["unclassified"]
    )


def _normalized_dates(values: Iterable[object]) -> pd.DatetimeIndex:
    parsed = pd.to_datetime(list(values), errors="coerce")
    return pd.DatetimeIndex(parsed).dropna().normalize()


def _missing_periods(missing_dates: pd.DatetimeIndex) -> tuple[MissingPeriod, ...]:
    if missing_dates.empty:
        return ()
    periods: list[MissingPeriod] = []
    start = previous = missing_dates[0]
    for current in missing_dates[1:]:
        if (current - previous).days > 1:
            periods.append(
                MissingPeriod(start.date().isoformat(), previous.date().isoformat(), (previous - start).days + 1)
            )
            start = current
        previous = current
    periods.append(
        MissingPeriod(start.date().isoformat(), previous.date().isoformat(), (previous - start).days + 1)
    )
    return tuple(periods)


def _event_summaries(
    daily: pd.DataFrame, antecedent_dry_days: float
) -> tuple[RainfallEventSummary, ...]:
    wet = daily.loc[daily["Precipitation"] > 0.0, ["Date", "Precipitation"]]
    if wet.empty:
        return ()
    threshold = max(float(antecedent_dry_days), 0.0)
    events: list[RainfallEventSummary] = []
    event_rows: list[tuple[pd.Timestamp, float]] = []

    def finish_event() -> None:
        if not event_rows:
            return
        start = event_rows[0][0]
        end = event_rows[-1][0]
        events.append(
            RainfallEventSummary(
                event_number=len(events) + 1,
                start=start.date().isoformat(),
                end=end.date().isoformat(),
                duration_days=(end - start).days + 1,
                wet_days=len(event_rows),
                precipitation=float(sum(value for _date, value in event_rows)),
            )
        )

    previous: pd.Timestamp | None = None
    for row in wet.itertuples(index=False):
        current = pd.Timestamp(row.Date)
        if previous is not None and (current - previous).total_seconds() / 86400.0 > threshold:
            finish_event()
            event_rows = []
        event_rows.append((current, float(row.Precipitation)))
        previous = current
    finish_event()
    return tuple(events)


def assess_rainfall_record(
    rainfall_df: pd.DataFrame,
    *,
    known_missing_dates: Iterable[object] = (),
    antecedent_dry_days: float = 1.0,
) -> RainfallQualityAssessment:
    """Assess daily rainfall coverage without changing the supplied record.

    Completeness is measured against complete calendar years spanning the first
    and last valid observations, so partial first or last years are visible
    instead of being hidden by an internally complete date range.
    """
    if rainfall_df.empty or "Date" not in rainfall_df:
        return RainfallQualityAssessment(
            None, None, 0, 0, 0, 0, 0, 0.0, "No data", (), (), (), ()
        )

    dates = pd.to_datetime(rainfall_df["Date"], errors="coerce")
    precipitation = pd.to_numeric(
        rainfall_df.get("Precipitation", pd.Series(index=rainfall_df.index, dtype=float)),
        errors="coerce",
    )
    valid_date_mask = dates.notna()
    finite_precipitation = precipitation.map(math.isfinite)
    invalid_precipitation = int(
        (valid_date_mask & ((~finite_precipitation) | (precipitation < 0.0))).sum()
    )
    normalized = dates.loc[valid_date_mask].dt.normalize()
    if normalized.empty:
        return RainfallQualityAssessment(
            None, None, 0, 0, 0, 0, invalid_precipitation, 0.0, "No data", (), (), (), ()
        )

    duplicate_dates = int(normalized.duplicated(keep="last").sum())
    daily = pd.DataFrame(
        {
            "Date": normalized,
            "Precipitation": precipitation.loc[valid_date_mask].fillna(0.0).clip(lower=0.0),
            "ValidPrecipitation": (
                finite_precipitation.loc[valid_date_mask]
                & (precipitation.loc[valid_date_mask] >= 0.0)
            ),
        }
    ).drop_duplicates(subset="Date", keep="last").sort_values("Date")

    known_missing = _normalized_dates(known_missing_dates)
    first_date = pd.Timestamp(daily["Date"].min())
    last_date = pd.Timestamp(daily["Date"].max())
    calendar_start = pd.Timestamp(year=first_date.year, month=1, day=1)
    calendar_end = pd.Timestamp(year=last_date.year, month=12, day=31)
    expected = pd.date_range(calendar_start, calendar_end, freq="D")
    observed = pd.DatetimeIndex(daily.loc[daily["ValidPrecipitation"], "Date"])
    observed = observed.difference(known_missing)
    missing = expected.difference(observed)
    observed_days = len(expected) - len(missing)
    completeness = 100.0 * observed_days / len(expected) if len(expected) else 0.0
    if completeness >= 99.5:
        rating = "Excellent"
    elif completeness >= 97.0:
        rating = "Good"
    elif completeness >= 90.0:
        rating = "Fair"
    else:
        rating = "Poor"

    yearly: list[YearlyRainfallSummary] = []
    partial_years: list[int] = []
    for year in range(calendar_start.year, calendar_end.year + 1):
        year_expected = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
        year_observed = observed[observed.year == year]
        missing_days = len(year_expected) - len(year_observed)
        if missing_days:
            partial_years.append(year)
        year_daily = daily.loc[daily["Date"].dt.year == year]
        yearly.append(
            YearlyRainfallSummary(
                year=year,
                expected_days=len(year_expected),
                observed_days=len(year_observed),
                missing_days=missing_days,
                completeness_percent=100.0 * len(year_observed) / len(year_expected),
                precipitation=float(year_daily["Precipitation"].sum()),
                wet_days=int((year_daily["Precipitation"] > 0.0).sum()),
                partial_year=bool(missing_days),
            )
        )

    event_daily = daily.loc[~daily["Date"].isin(known_missing)]
    return RainfallQualityAssessment(
        record_start=first_date.date().isoformat(),
        record_end=last_date.date().isoformat(),
        expected_days=len(expected),
        observed_days=observed_days,
        missing_days=len(missing),
        duplicate_dates=duplicate_dates,
        invalid_precipitation_rows=invalid_precipitation,
        completeness_percent=completeness,
        completeness_rating=rating,
        partial_years=tuple(partial_years),
        missing_periods=_missing_periods(missing),
        yearly_summaries=tuple(yearly),
        event_summaries=_event_summaries(event_daily, antecedent_dry_days),
    )
