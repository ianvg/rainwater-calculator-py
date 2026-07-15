from __future__ import annotations

from calendar import monthrange
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from .models import DemandProfile, MONTH_KEYS, ProjectConfig, TankParameters

GAL_PER_CUBIC_FOOT = 7.48052


def _validate_rainfall(rainfall_df: pd.DataFrame) -> pd.DataFrame:
    if "Date" not in rainfall_df.columns or "Precipitation" not in rainfall_df.columns:
        raise ValueError("Rainfall data must contain 'Date' and 'Precipitation' columns.")

    data = rainfall_df.copy()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data["Precipitation"] = pd.to_numeric(data["Precipitation"], errors="coerce").fillna(0.0)
    data = data.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    return data


def _month_index_key(ts: pd.Timestamp) -> str:
    return MONTH_KEYS[ts.month - 1]


def _daily_demand_for_date(demand: DemandProfile, date: pd.Timestamp) -> float:
    m = _month_index_key(date)
    days = monthrange(date.year, date.month)[1]

    toilet_daily = demand.female_occupancy[m] * demand.avg_flush_per_person * demand.gallons_per_flush_toilet
    toilet_daily += 0.5 * demand.male_occupancy[m] * demand.avg_flush_per_person * demand.gallons_per_flush_toilet

    urinal_daily = 0.5 * demand.male_occupancy[m] * demand.avg_flush_per_person * demand.gallons_per_flush_urinal

    monthly_other = (
        demand.ice_making[m]
        + demand.cooling_tower[m]
        + demand.ice_skating[m]
        + demand.other_indoor[m]
        + demand.spray_irrigation[m]
        + demand.drip_irrigation[m]
        + demand.vehicular_washing[m]
        + demand.other_outdoor[m]
    )

    simple_daily = max(float(getattr(demand, "simple_daily_demand_gallons", 0.0)), 0.0)
    operating_days = min(max(int(getattr(demand, "daily_demand_days_per_week", 7)), 0), 7)
    recurring_daily = simple_daily + toilet_daily + urinal_daily
    if date.weekday() >= operating_days:
        recurring_daily = 0.0

    return float(recurring_daily + (monthly_other / days))


def collected_water_series(config: ProjectConfig, rainfall_df: pd.DataFrame) -> pd.Series:
    data = _validate_rainfall(rainfall_df)

    areas = np.array([max(0.0, s.area) for s in config.surfaces], dtype=float)
    coeffs = np.array([min(max(0.0, s.runoff_coefficient), 1.0) for s in config.surfaces], dtype=float)

    collected_gallons: list[float] = []
    precip = data["Precipitation"].to_numpy(dtype=float)

    for i in range(len(precip)):
        effective_areas = areas
        if i > 3 and precip[i - 1] <= 0 and precip[i - 2] <= 0 and precip[i - 3] <= 0:
            effective_areas = areas - (areas * 0.00138)

        rainfall_feet = precip[i] / 12.0
        gallons = float(np.sum(effective_areas * coeffs * rainfall_feet) * GAL_PER_CUBIC_FOOT)
        collected_gallons.append(max(0.0, gallons))

    return pd.Series(collected_gallons, index=data.index, name="collected_gallons")


def demand_series(config: ProjectConfig, rainfall_df: pd.DataFrame) -> pd.Series:
    data = _validate_rainfall(rainfall_df)
    values = [_daily_demand_for_date(config.demand, d) for d in data["Date"]]
    return pd.Series(values, index=data.index, name="demand_gallons")


def simulate_tank(
    config: ProjectConfig,
    rainfall_df: pd.DataFrame,
    tank_size_gallons: float,
    tank_parameters: TankParameters | None = None,
) -> pd.DataFrame:
    if tank_size_gallons <= 0:
        raise ValueError("Tank size must be greater than zero.")

    params = tank_parameters or config.tank_parameters
    data = _validate_rainfall(rainfall_df)
    collected = collected_water_series(config, data)
    demand = demand_series(config, data)

    initial_fill = min(max(params.initial_fill_percent / 100.0, 0.0), 1.0)
    reserve_fraction = min(max(params.reliable_fill_percent / 100.0, 0.0), 1.0)
    water_level: list[float] = []
    demand_met: list[bool] = []
    reserve_target_met: list[bool] = []
    unmet_demand: list[float] = []
    overflow: list[float] = []
    reliable_days = 0

    for i in range(len(data)):
        if i == 0:
            water = (tank_size_gallons * initial_fill) + collected.iloc[i]
        else:
            water = water_level[-1] + collected.iloc[i]

        water = max(water, 0.0)
        overflow_today = max(water - tank_size_gallons, 0.0)
        water = min(water, tank_size_gallons)
        demand_today = max(float(demand.iloc[i]), 0.0)
        reserve_target = demand_today * (1.0 + reserve_fraction)
        met_today = water >= demand_today
        reserve_met_today = water >= reserve_target
        unmet_today = max(demand_today - water, 0.0)
        water = max(water - demand_today, 0.0)

        water_level.append(float(water))
        demand_met.append(bool(met_today))
        reserve_target_met.append(bool(reserve_met_today))
        unmet_demand.append(float(unmet_today))
        overflow.append(float(overflow_today))

        if met_today:
            reliable_days += 1

    reliability = (reliable_days / len(data)) * 100 if len(data) else 0.0

    return pd.DataFrame(
        {
            "Date": data["Date"],
            "Precipitation": data["Precipitation"],
            "CollectedGallons": collected,
            "DemandGallons": demand,
            "DemandMet": demand_met,
            "ReserveTargetMet": reserve_target_met,
            "UnmetDemandGallons": unmet_demand,
            "OverflowGallons": overflow,
            "WaterInTankGallons": water_level,
        }
    ).assign(ReliabilityPercent=reliability)


def reliability_curve(
    config: ProjectConfig,
    rainfall_df: pd.DataFrame,
    tank_sizes_gallons: Iterable[float],
    tank_parameters: TankParameters | None = None,
    progress_callback: Callable[[int, int, float], None] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    tank_sizes = list(tank_sizes_gallons)
    total = len(tank_sizes)
    for index, tank_size in enumerate(tank_sizes, start=1):
        result = simulate_tank(config, rainfall_df, tank_size, tank_parameters=tank_parameters)
        reliability = float(result["ReliabilityPercent"].iloc[0]) if not result.empty else 0.0
        rows.append({"TankSizeGallons": float(tank_size), "ReliabilityPercent": reliability})
        if progress_callback is not None:
            progress_callback(index, total, float(tank_size))

    return pd.DataFrame(rows)
