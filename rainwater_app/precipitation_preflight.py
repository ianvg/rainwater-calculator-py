from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable

import pandas as pd

from .acis import fetch_daily_station_data
from .eccc import fetch_canadian_daily_station_data


DailyStationLoader = Callable[[str, date, date, str], pd.DataFrame]


@dataclass(frozen=True)
class StationCoverage:
    station_id: str
    station_name: str
    provider: str
    requested_start: date
    requested_end: date
    expected_days: int
    observed_days: int
    missing_days: int
    completeness_percent: float
    record_start: date | None
    record_end: date | None
    error: str = ""

    @property
    def available(self) -> bool:
        return not self.error


def assess_station_coverage(
    station: dict[str, object],
    start_date: date,
    end_date: date,
    precipitation_field: str,
    loader: DailyStationLoader,
) -> StationCoverage:
    """Download one station record and measure valid daily coverage."""
    if end_date < start_date:
        raise ValueError("Coverage end date must not precede its start date.")

    station_id = str(station.get("sid") or "").strip()
    station_name = str(station.get("name") or "Unnamed station").strip()
    provider = str(station.get("provider") or "").strip().upper()
    expected = pd.date_range(start_date, end_date, freq="D")

    try:
        rainfall = loader(station_id, start_date, end_date, precipitation_field)
        dates = pd.to_datetime(rainfall.get("Date"), errors="coerce")
        precipitation = pd.to_numeric(rainfall.get("Precipitation"), errors="coerce")
        valid = pd.DataFrame({"Date": dates, "Precipitation": precipitation}).dropna()
        valid = valid.loc[valid["Precipitation"] >= 0.0]
        observed = pd.DatetimeIndex(valid["Date"]).normalize().unique()
        known_missing = pd.DatetimeIndex(
            pd.to_datetime(
                rainfall.attrs.get("known_missing_dates", []), errors="coerce"
            )
        ).dropna().normalize()
        observed = observed.difference(known_missing).intersection(expected)
        record_dates = pd.DatetimeIndex(dates.dropna()).normalize()
        observed_days = len(observed)
        return StationCoverage(
            station_id=station_id,
            station_name=station_name,
            provider=provider,
            requested_start=start_date,
            requested_end=end_date,
            expected_days=len(expected),
            observed_days=observed_days,
            missing_days=len(expected) - observed_days,
            completeness_percent=(100.0 * observed_days / len(expected)),
            record_start=(record_dates.min().date() if len(record_dates) else None),
            record_end=(record_dates.max().date() if len(record_dates) else None),
        )
    except Exception as exc:  # noqa: BLE001 - one failed station must not abort the comparison
        return StationCoverage(
            station_id=station_id,
            station_name=station_name,
            provider=provider,
            requested_start=start_date,
            requested_end=end_date,
            expected_days=len(expected),
            observed_days=0,
            missing_days=len(expected),
            completeness_percent=0.0,
            record_start=None,
            record_end=None,
            error=str(exc),
        )


def compare_station_coverage(
    stations: Iterable[dict[str, object]],
    start_date: date,
    end_date: date,
    precipitation_field: str = "TOTAL_PRECIPITATION",
    *,
    loaders: dict[str, DailyStationLoader] | None = None,
    max_workers: int = 4,
) -> list[StationCoverage]:
    """Assess candidates concurrently and rank usable records by completeness."""
    candidates = list(stations)
    provider_loaders = loaders or {
        "ACIS": fetch_daily_station_data,
        "ECCC": fetch_canadian_daily_station_data,
    }

    def assess(station: dict[str, object]) -> StationCoverage:
        provider = str(station.get("provider") or "").strip().upper()
        loader = provider_loaders.get(provider)
        if loader is None:
            def unsupported_loader(
                _station_id: str,
                _start_date: date,
                _end_date: date,
                _field: str,
            ) -> pd.DataFrame:
                raise ValueError(f"Unsupported precipitation provider: {provider or 'unknown'}")

            loader = unsupported_loader
        return assess_station_coverage(
            station, start_date, end_date, precipitation_field, loader
        )

    results: list[StationCoverage] = []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(candidates) or 1))) as executor:
        futures = [executor.submit(assess, station) for station in candidates]
        for future in as_completed(futures):
            results.append(future.result())

    return sorted(
        results,
        key=lambda result: (
            not result.available,
            -result.completeness_percent,
            result.station_name.casefold(),
            result.station_id,
        ),
    )
