from __future__ import annotations

from calendar import monthrange
from copy import deepcopy
from dataclasses import dataclass, replace
import math
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from .models import (
    DemandProfile,
    MONTH_KEYS,
    ProjectConfig,
    TankParameters,
    WEEKDAY_KEYS,
    fixture_daily_demand_gallons,
    schedule_months_for,
)
from .rainfall import expand_hourly_rainfall
from .system_model import compile_builder_system

GAL_PER_CUBIC_FOOT = 7.48052


class AnalysisCancelledError(RuntimeError):
    """Raised when a running simulation is cooperatively cancelled."""


def _operating_fraction(value: object, label: str) -> float:
    try:
        percent = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a valid percentage.") from exc
    if not math.isfinite(percent) or not 0.0 <= percent < 100.0:
        raise ValueError(f"{label} must be at least 0% and less than 100%.")
    return percent / 100.0


def _buffer_needs_refill(
    water: float, refill_target: float, minimum_operating_volume: float
) -> bool:
    if minimum_operating_volume > 0.0 and refill_target <= minimum_operating_volume:
        return water <= minimum_operating_volume + 1e-9
    return water < refill_target


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


def _base_daily_demand_for_date(demand: DemandProfile, date: pd.Timestamp) -> float:
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


def _schedule_fractions_for_date(
    schedule: dict[str, list[float]], date: pd.Timestamp
) -> list[float]:
    day_key = WEEKDAY_KEYS[date.weekday()]
    values = [min(max(float(value), 0.0), 1.0) for value in schedule.get(day_key, [])[:24]]
    values.extend([0.0] * (24 - len(values)))
    total = sum(values)
    return [value / total for value in values] if total > 0.0 else [0.0] * 24


def _demand_object_daily_value_for_date(
    demand: DemandProfile, demand_object, date: pd.Timestamp
) -> float:
    mode = getattr(demand_object, "demand_mode", "scheduled_flow")
    schedule = demand.hourly_schedule_library.get(demand_object.schedule_name)
    if schedule is None and mode != "monthly_volume":
        return 0.0
    if (
        schedule is not None
        and date.month not in schedule_months_for(demand, demand_object.schedule_name)
    ):
        return 0.0
    if mode == "recurring_daily":
        day_key = WEEKDAY_KEYS[date.weekday()]
        occupied = any(
            float(value) > 0.0 for value in schedule.get(day_key, [])[:24]
        )
        daily_volume = demand_object.monthly_daily_demand_gallons.get(
            _month_index_key(date), demand_object.recurring_daily_gallons
        )
        return (
            max(float(daily_volume), 0.0)
            if occupied
            else 0.0
        )
    if mode == "fixture_usage":
        day_key = WEEKDAY_KEYS[date.weekday()]
        day_weights = [
            min(max(float(value), 0.0), 1.0)
            for value in schedule.get(day_key, [])[:24]
        ]
        return (
            fixture_daily_demand_gallons(demand_object)
            if any(day_weights)
            else 0.0
        )
    if mode == "monthly_volume":
        monthly = max(
            float(demand_object.monthly_demand_gallons.get(_month_index_key(date), 0.0)),
            0.0,
        )
        return monthly / monthrange(date.year, date.month)[1]
    day_key = WEEKDAY_KEYS[date.weekday()]
    multipliers = [
        min(max(float(value), 0.0), 1.0)
        for value in schedule.get(day_key, [])[:24]
    ]
    return (
        max(float(demand_object.instantaneous_demand_gallons_per_minute), 0.0)
        * 60.0
        * sum(multipliers)
    )


def _demand_object_daily_for_date(demand: DemandProfile, date: pd.Timestamp) -> float:
    return sum(
        _demand_object_daily_value_for_date(demand, demand_object, date)
        for demand_object in demand.demand_objects
    )


def demand_object_daily_value_for_date(
    demand: DemandProfile, demand_object, date: pd.Timestamp
) -> float:
    """Return one demand object's simulated daily demand for reporting and audits."""
    return _demand_object_daily_value_for_date(demand, demand_object, pd.Timestamp(date))


def demand_object_sewer_eligible_fraction(
    demand_object, legacy_eligible_percent: float
) -> float:
    """Return the sewer-savings fraction applied to a demand object."""
    return _demand_object_sewer_eligible_fraction(demand_object, legacy_eligible_percent)


def _demand_object_sewer_eligible_fraction(
    demand_object, legacy_eligible_percent: float
) -> float:
    if bool(getattr(demand_object, "uses_legacy_sewer_eligibility", False)):
        return min(max(float(legacy_eligible_percent), 0.0), 100.0) / 100.0
    return 1.0 if bool(getattr(demand_object, "sewer_eligible", True)) else 0.0


def _demand_object_hourly_for_date(
    demand: DemandProfile, demand_object, date: pd.Timestamp
) -> np.ndarray:
    mode = getattr(demand_object, "demand_mode", "scheduled_flow")
    schedule = demand.hourly_schedule_library.get(demand_object.schedule_name)
    if schedule is None:
        if mode == "monthly_volume" and not demand_object.schedule_name:
            schedule = {day: [1.0] * 24 for day in WEEKDAY_KEYS}
        else:
            return np.zeros(24, dtype=np.float64)
    elif date.month not in schedule_months_for(demand, demand_object.schedule_name):
        return np.zeros(24, dtype=np.float64)
    day_key = WEEKDAY_KEYS[date.weekday()]
    multipliers = [
        min(max(float(value), 0.0), 1.0)
        for value in schedule.get(day_key, [])[:24]
    ]
    multipliers.extend([0.0] * (24 - len(multipliers)))
    if mode == "scheduled_flow":
        flow = max(float(demand_object.instantaneous_demand_gallons_per_minute), 0.0)
        return np.asarray(multipliers, dtype=np.float64) * flow * 60.0
    daily_volume = 0.0
    if mode == "recurring_daily":
        if any(multipliers):
            daily_value = demand_object.monthly_daily_demand_gallons.get(
                _month_index_key(date), demand_object.recurring_daily_gallons
            )
            daily_volume = max(
                float(daily_value), 0.0
            )
    elif mode == "fixture_usage":
        if any(multipliers):
            daily_volume = fixture_daily_demand_gallons(demand_object)
    elif mode == "monthly_volume":
        monthly = max(float(demand_object.monthly_demand_gallons.get(_month_index_key(date), 0.0)), 0.0)
        daily_volume = monthly / monthrange(date.year, date.month)[1]
    total_multiplier = sum(multipliers)
    if mode == "fixture_usage" and total_multiplier > 0.0:
        occupied = np.asarray(
            [1.0 if value > 0.0 else 0.0 for value in multipliers],
            dtype=np.float64,
        )
        fractions = occupied / float(occupied.sum())
    elif total_multiplier > 0.0:
        fractions = np.asarray(multipliers, dtype=np.float64) / total_multiplier
    elif mode == "fixture_usage":
        fractions = np.zeros(24, dtype=np.float64)
    else:
        fractions = np.full(24, 1.0 / 24.0)
    return fractions * daily_volume


def _daily_demand_for_date(demand: DemandProfile, date: pd.Timestamp) -> float:
    return _base_daily_demand_for_date(demand, date) + _demand_object_daily_for_date(demand, date)


def _sewer_eligible_daily_demand_for_date(
    demand: DemandProfile, date: pd.Timestamp, legacy_eligible_percent: float
) -> float:
    legacy_eligible = (
        _base_daily_demand_for_date(demand, date)
        * min(max(float(legacy_eligible_percent), 0.0), 100.0)
        / 100.0
    )
    object_eligible = sum(
        _demand_object_daily_value_for_date(demand, demand_object, date)
        * _demand_object_sewer_eligible_fraction(
            demand_object, legacy_eligible_percent
        )
        for demand_object in demand.demand_objects
    )
    return float(legacy_eligible + object_eligible)


def collection_balance_series(config: ProjectConfig, rainfall_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate gross runoff, rainfall-history first flush, and net collection.

    A wet observation begins a new event when it is the first wet observation or
    when the elapsed time since the preceding wet observation exceeds the
    configured antecedent dry period. On the first wet observation of an event,
    each surface diverts up to its configured first-flush depth. Consecutive wet
    observations do not divert another first flush (Khan's Model 2).
    """
    data = _validate_rainfall(rainfall_df)
    areas = np.array([max(0.0, s.area) for s in config.surfaces], dtype=float)
    coeffs = np.array([min(max(0.0, s.runoff_coefficient), 1.0) for s in config.surfaces], dtype=float)
    system = compile_builder_system(
        config.system_type, config.system_layout, config.system_connections
    )
    diversion_depths = np.array(
        [
            max(float(s.first_flush_depth_inches), 0.0)
            if system.first_flush_path else 0.0
            for s in config.surfaces
        ],
        dtype=float,
    )
    diversion_allowances = (
        areas * coeffs * diversion_depths / 12.0 * GAL_PER_CUBIC_FOOT
    )
    antecedent = pd.Timedelta(days=max(float(config.first_flush_antecedent_dry_days), 0.0))
    dates = data["Date"].to_numpy(dtype="datetime64[ns]", copy=False)
    precip = np.maximum(data["Precipitation"].to_numpy(dtype=float), 0.0)
    wet = precip > 0.0
    wet_indices = np.flatnonzero(wet)
    event_starts = np.zeros(len(data), dtype=bool)
    if wet_indices.size:
        wet_dates = dates[wet_indices]
        wet_starts = np.ones(wet_indices.size, dtype=bool)
        if wet_indices.size > 1:
            wet_starts[1:] = np.diff(wet_dates) > antecedent.to_timedelta64()
        event_starts[wet_indices] = wet_starts

    event_numbers = np.cumsum(event_starts, dtype=np.int64)
    event_ids = pd.array(
        np.where(wet, event_numbers, 0), dtype="Int64"
    )
    event_ids[~wet] = pd.NA

    runoff_factors = areas * coeffs / 12.0 * GAL_PER_CUBIC_FOOT
    gross_values = precip * float(runoff_factors.sum())
    loss_values = np.zeros(len(data), dtype=float)
    start_indices = np.flatnonzero(event_starts)
    if start_indices.size and runoff_factors.size:
        start_runoff = precip[start_indices, None] * runoff_factors[None, :]
        loss_values[start_indices] = np.minimum(
            start_runoff, diversion_allowances[None, :]
        ).sum(axis=1)
    net_values = np.maximum(gross_values - loss_values, 0.0)
    return pd.DataFrame(
        {
            "GrossCollectedGallons": gross_values,
            "FirstFlushLossGallons": loss_values,
            "CollectedGallons": net_values,
            "RainfallEventId": event_ids,
            "RainfallEventStart": event_starts,
        },
        index=data.index,
    )


def collected_water_series(config: ProjectConfig, rainfall_df: pd.DataFrame) -> pd.Series:
    return collection_balance_series(config, rainfall_df)["CollectedGallons"].rename(
        "collected_gallons"
    )


def demand_series(config: ProjectConfig, rainfall_df: pd.DataFrame) -> pd.Series:
    data = _validate_rainfall(rainfall_df)
    values = [_daily_demand_for_date(config.demand, d) for d in data["Date"]]
    return pd.Series(values, index=data.index, name="demand_gallons")


def sewer_eligible_demand_series(
    config: ProjectConfig, rainfall_df: pd.DataFrame
) -> pd.Series:
    data = _validate_rainfall(rainfall_df)
    values = [
        _sewer_eligible_daily_demand_for_date(
            config.demand, date, config.financial_parameters.sewer_eligible_percent
        )
        for date in data["Date"]
    ]
    return pd.Series(values, index=data.index, name="sewer_eligible_demand_gallons")


@dataclass(frozen=True)
class PreparedDailyInputs:
    """Candidate-independent arrays shared by daily tank simulations."""

    dates: np.ndarray
    precipitation: np.ndarray
    gross_collected_gallons: np.ndarray
    first_flush_loss_gallons: np.ndarray
    collected_gallons: np.ndarray
    rainfall_event_ids: np.ndarray
    rainfall_event_starts: np.ndarray
    demand_gallons: np.ndarray
    sewer_eligible_demand_gallons: np.ndarray
    year_count: int


def prepare_daily_inputs(
    config: ProjectConfig, rainfall_df: pd.DataFrame
) -> PreparedDailyInputs:
    """Validate and calculate all daily inputs that do not depend on tank size."""
    data = _validate_rainfall(rainfall_df)
    collection = collection_balance_series(config, data)
    dates = data["Date"].to_numpy(dtype="datetime64[ns]", copy=True)
    demand = np.fromiter(
        (_daily_demand_for_date(config.demand, pd.Timestamp(date)) for date in dates),
        dtype=np.float64,
        count=len(dates),
    )
    sewer_eligible = np.fromiter(
        (
            _sewer_eligible_daily_demand_for_date(
                config.demand,
                pd.Timestamp(date),
                config.financial_parameters.sewer_eligible_percent,
            )
            for date in dates
        ),
        dtype=np.float64,
        count=len(dates),
    )
    years = pd.DatetimeIndex(dates).year
    return PreparedDailyInputs(
        dates=dates,
        precipitation=data["Precipitation"].to_numpy(dtype=float, copy=True),
        gross_collected_gallons=collection["GrossCollectedGallons"].to_numpy(
            dtype=float, copy=True
        ),
        first_flush_loss_gallons=collection["FirstFlushLossGallons"].to_numpy(
            dtype=float, copy=True
        ),
        collected_gallons=collection["CollectedGallons"].to_numpy(
            dtype=float, copy=True
        ),
        rainfall_event_ids=collection["RainfallEventId"].to_numpy(copy=True),
        rainfall_event_starts=collection["RainfallEventStart"].to_numpy(
            dtype=bool, copy=True
        ),
        demand_gallons=demand,
        sewer_eligible_demand_gallons=sewer_eligible,
        year_count=max(int(pd.Index(years).nunique()), 1),
    )


@dataclass(frozen=True)
class PreparedHourlyInputs:
    demand_gallons: np.ndarray
    sewer_eligible_demand_gallons: np.ndarray
    collected_gallons: np.ndarray
    year_indices: np.ndarray
    year_count: int


@dataclass(frozen=True)
class HourlySimulationAggregates:
    reliability_percent: float
    average_annual_supplied_gallons: float
    average_annual_sewer_eligible_supplied_gallons: float
    average_annual_municipal_makeup_gallons: float
    average_annual_overflow_gallons: float
    average_annual_pump_flow_gallons: float


def prepare_hourly_inputs(config: ProjectConfig, rainfall_df: pd.DataFrame) -> PreparedHourlyInputs:
    """Precompute candidate-independent demand, collection, and year arrays.

    Hourly demand timing follows the saved profile.  Daily demand timing retains
    that profile, sums its 24 values, and applies the total at 12:00.
    """
    data = _validate_rainfall(rainfall_df)
    hourly_rainfall = expand_hourly_rainfall(
        data, use_synthetic=config.use_synthetic_hourly_rainfall
    )
    hourly_collected = collected_water_series(config, hourly_rainfall).to_numpy(dtype=float)
    demand_values = np.zeros(len(data) * 24, dtype=np.float64)
    sewer_eligible_demand_values = np.zeros(len(data) * 24, dtype=np.float64)
    collected_values = np.zeros(len(data) * 24, dtype=np.float64)
    years = np.zeros(len(data) * 24, dtype=np.int32)
    schedule = config.demand.hourly_schedule_library.get(
        config.demand.active_hourly_schedule_name,
        config.demand.hourly_weekly_fractions,
    )
    for day_index, date in enumerate(data["Date"]):
        timestamp = pd.Timestamp(date)
        fractions = _schedule_fractions_for_date(schedule, timestamp)
        if not any(fractions):
            fractions = [1.0 / 24.0] * 24
        object_demands = np.zeros(24, dtype=np.float64)
        sewer_eligible_object_demands = np.zeros(24, dtype=np.float64)
        for demand_object in config.demand.demand_objects:
            values = _demand_object_hourly_for_date(
                config.demand, demand_object, timestamp
            )
            object_demands += values
            sewer_eligible_object_demands += values * _demand_object_sewer_eligible_fraction(
                demand_object, config.financial_parameters.sewer_eligible_percent
            )
        start = day_index * 24
        legacy_daily = max(_base_daily_demand_for_date(config.demand, timestamp), 0.0)
        fraction_values = np.asarray(fractions)
        daily_demand_values = legacy_daily * fraction_values + object_demands
        daily_sewer_eligible_values = (
            legacy_daily
            * min(max(config.financial_parameters.sewer_eligible_percent, 0.0), 100.0)
            / 100.0
            * fraction_values
            + sewer_eligible_object_demands
        )
        if config.demand.hourly_schedule_enabled:
            demand_values[start:start + 24] = daily_demand_values
            sewer_eligible_demand_values[start:start + 24] = daily_sewer_eligible_values
        else:
            demand_values[start + 12] = float(daily_demand_values.sum())
            sewer_eligible_demand_values[start + 12] = float(
                daily_sewer_eligible_values.sum()
            )
        collected_values[start:start + 24] = hourly_collected[start:start + 24]
        years[start:start + 24] = timestamp.year
    _unique_years, year_indices = np.unique(years, return_inverse=True)
    return PreparedHourlyInputs(
        demand_gallons=demand_values,
        sewer_eligible_demand_gallons=sewer_eligible_demand_values,
        collected_gallons=collected_values,
        year_indices=year_indices.astype(np.int32, copy=False),
        year_count=max(len(_unique_years), 1),
    )


def simulate_hourly_indirect_aggregates(
    config: ProjectConfig,
    prepared: PreparedHourlyInputs,
    tank_size_gallons: float,
    cancel_callback: Callable[[], bool] | None = None,
) -> HourlySimulationAggregates:
    """Run the indirect hourly mass balance without constructing timestep result rows."""
    if tank_size_gallons <= 0.0:
        raise ValueError("Tank size must be greater than zero.")
    params = config.system_parameters
    pump_capacity = params.transfer_pump_capacity_gallons_per_hour
    recovery = min(max(float(params.filter_recovery_percent) / 100.0, 0.0), 1.0)
    booster_capacity = max(float(params.booster_tank_size_gallons), 0.0)
    booster_water = booster_capacity * min(max(float(params.booster_initial_fill_percent) / 100.0, 0.0), 1.0)
    booster_rainwater = booster_water
    booster_municipal = 0.0
    booster_minimum_fraction = _operating_fraction(
        params.booster_minimum_operating_volume_percent,
        "Buffer minimum operating level",
    )
    booster_minimum_volume = booster_capacity * booster_minimum_fraction
    refill_target = booster_capacity * min(max(float(params.booster_refill_level_percent) / 100.0, 0.0), 1.0)
    refill_active = booster_capacity > 0.0 and _buffer_needs_refill(
        booster_water, refill_target, booster_minimum_volume
    )
    water = tank_size_gallons * min(max(config.tank_parameters.initial_fill_percent / 100.0, 0.0), 1.0)
    minimum_volume = tank_size_gallons * _operating_fraction(
        config.tank_parameters.minimum_operating_volume_percent,
        "Primary minimum operating level",
    )
    annual_supplied = np.zeros(prepared.year_count, dtype=np.float64)
    annual_sewer_eligible_supplied = np.zeros(prepared.year_count, dtype=np.float64)
    annual_makeup = np.zeros(prepared.year_count, dtype=np.float64)
    annual_overflow = np.zeros(prepared.year_count, dtype=np.float64)
    annual_pump = np.zeros(prepared.year_count, dtype=np.float64)
    met_hours = 0
    for index in range(prepared.demand_gallons.size):
        if cancel_callback is not None and index % 256 == 0 and cancel_callback():
            raise AnalysisCancelledError("Analysis cancelled by user.")
        demand = max(float(prepared.demand_gallons[index]), 0.0)
        sewer_eligible_demand = min(
            max(float(prepared.sewer_eligible_demand_gallons[index]), 0.0), demand
        )
        pump_flow = 0.0
        mains_makeup = 0.0
        if booster_capacity > 0.0:
            if refill_active:
                booster_space = max(booster_capacity - booster_water, 0.0)
                delivered_capacity = pump_capacity * recovery if pump_capacity > 0.0 else booster_space
                requested_delivery = min(booster_space, delivered_capacity)
                requested_input = requested_delivery / recovery if recovery > 0.0 else 0.0
                pump_flow = min(max(water - minimum_volume, 0.0), requested_input)
                if pump_capacity > 0.0:
                    pump_flow = min(pump_flow, pump_capacity)
                filtered = pump_flow * recovery
                water = max(water - pump_flow, 0.0)
                if params.municipal_backup_enabled:
                    mains_makeup = max(requested_delivery - filtered, 0.0)
                booster_rainwater += filtered
                booster_municipal += mains_makeup
                booster_water = min(booster_rainwater + booster_municipal, booster_capacity)
                if booster_water >= booster_capacity - 1e-9:
                    refill_active = False
            total_before_demand = booster_water
            total_supplied = min(
                max(total_before_demand - booster_minimum_volume, 0.0), demand
            )
            rainwater_fraction = booster_rainwater / total_before_demand if total_before_demand > 0.0 else 0.0
            rainwater_supplied = total_supplied * rainwater_fraction
            mains_supplied = total_supplied - rainwater_supplied
            booster_rainwater = max(booster_rainwater - rainwater_supplied, 0.0)
            booster_municipal = max(booster_municipal - mains_supplied, 0.0)
            booster_water = booster_rainwater + booster_municipal
            if _buffer_needs_refill(
                booster_water, refill_target, booster_minimum_volume
            ):
                refill_active = True
        else:
            requested_input = demand / recovery if recovery > 0.0 else 0.0
            pump_flow = min(max(water - minimum_volume, 0.0), requested_input)
            if pump_capacity > 0.0:
                pump_flow = min(pump_flow, pump_capacity)
            rainwater_supplied = min(pump_flow * recovery, demand)
            water = max(water - pump_flow, 0.0)
            if params.municipal_backup_enabled:
                mains_makeup = max(demand - rainwater_supplied, 0.0)
        met_hours += int(rainwater_supplied >= demand)
        water += float(prepared.collected_gallons[index])
        overflow = max(water - tank_size_gallons, 0.0)
        water = min(max(water, 0.0), tank_size_gallons)
        year_index = int(prepared.year_indices[index])
        annual_supplied[year_index] += rainwater_supplied
        annual_sewer_eligible_supplied[year_index] += (
            rainwater_supplied * sewer_eligible_demand / demand if demand > 0.0 else 0.0
        )
        annual_makeup[year_index] += mains_makeup
        annual_overflow[year_index] += overflow
        annual_pump[year_index] += pump_flow
    count = prepared.demand_gallons.size
    return HourlySimulationAggregates(
        reliability_percent=met_hours / count * 100.0 if count else 0.0,
        average_annual_supplied_gallons=float(annual_supplied.mean()) if annual_supplied.size else 0.0,
        average_annual_sewer_eligible_supplied_gallons=(
            float(annual_sewer_eligible_supplied.mean())
            if annual_sewer_eligible_supplied.size else 0.0
        ),
        average_annual_municipal_makeup_gallons=float(annual_makeup.mean()) if annual_makeup.size else 0.0,
        average_annual_overflow_gallons=float(annual_overflow.mean()) if annual_overflow.size else 0.0,
        average_annual_pump_flow_gallons=float(annual_pump.mean()) if annual_pump.size else 0.0,
    )


def simulate_tank(
    config: ProjectConfig,
    rainfall_df: pd.DataFrame,
    tank_size_gallons: float,
    tank_parameters: TankParameters | None = None,
    cancel_callback: Callable[[], bool] | None = None,
    prepared_inputs: PreparedDailyInputs | None = None,
) -> pd.DataFrame:
    if tank_size_gallons <= 0:
        raise ValueError("Tank size must be greater than zero.")

    params = tank_parameters or config.tank_parameters
    if prepared_inputs is None:
        data = _validate_rainfall(rainfall_df)
        collection = collection_balance_series(config, data)
        demand = demand_series(config, data)
        sewer_eligible_demand = sewer_eligible_demand_series(config, data)
    else:
        prepared = prepared_inputs
        data = pd.DataFrame(
            {
                "Date": prepared.dates,
                "Precipitation": prepared.precipitation,
            }
        )
        collection = pd.DataFrame(
            {
                "GrossCollectedGallons": prepared.gross_collected_gallons,
                "FirstFlushLossGallons": prepared.first_flush_loss_gallons,
                "CollectedGallons": prepared.collected_gallons,
                "RainfallEventId": pd.array(
                    prepared.rainfall_event_ids, dtype="Int64"
                ),
                "RainfallEventStart": prepared.rainfall_event_starts,
            }
        )
        demand = pd.Series(prepared.demand_gallons, name="demand_gallons")
        sewer_eligible_demand = pd.Series(
            prepared.sewer_eligible_demand_gallons,
            name="sewer_eligible_demand_gallons",
        )
    system = compile_builder_system(
        config.system_type, config.system_layout, config.system_connections
    )
    if not system.rain_reaches_primary:
        collection.loc[:, [
            "GrossCollectedGallons", "FirstFlushLossGallons", "CollectedGallons"
        ]] = 0.0
    collected = collection["CollectedGallons"]

    initial_fill = min(max(params.initial_fill_percent / 100.0, 0.0), 1.0)
    minimum_operating_fraction = _operating_fraction(
        params.minimum_operating_volume_percent,
        "Primary minimum operating level",
    )
    minimum_operating_volume = tank_size_gallons * minimum_operating_fraction
    water_level: list[float] = []
    demand_met: list[bool] = []
    usable_water_available: list[float] = []
    operating_reserve_stored: list[float] = []
    unmet_demand: list[float] = []
    supplied_demand: list[float] = []
    sewer_eligible_supplied: list[float] = []
    municipal_makeup: list[float] = []
    system_unmet_demand: list[float] = []
    reserve_unmet_demand: list[float] = []
    treatment_loss: list[float] = []
    pump_flow: list[float] = []
    overflow: list[float] = []
    reliable_days = 0

    for i in range(len(data)):
        if cancel_callback is not None and i % 100 == 0 and cancel_callback():
            raise AnalysisCancelledError("Analysis cancelled by user.")
        if i == 0:
            water = tank_size_gallons * initial_fill
        else:
            water = water_level[-1]

        water = min(max(water, 0.0), tank_size_gallons)
        demand_today = max(float(demand.iloc[i]), 0.0)
        sewer_eligible_demand_today = min(
            max(float(sewer_eligible_demand.iloc[i]), 0.0), demand_today
        )
        available_for_withdrawal = max(water - minimum_operating_volume, 0.0)
        supplied_today = 0.0
        unrestricted_supplied_today = 0.0
        withdrawn_today = 0.0
        if system.primary_reaches_end_uses:
            if system.filtration_path:
                recovery = min(
                    max(config.system_parameters.filter_recovery_percent / 100.0, 0.0), 1.0
                )
                requested_input = demand_today / recovery if recovery > 0.0 else 0.0
                daily_capacity = max(
                    config.system_parameters.transfer_pump_capacity_gallons_per_hour, 0.0
                ) * 24.0
                withdrawn_today = min(available_for_withdrawal, requested_input)
                if daily_capacity > 0.0:
                    withdrawn_today = min(withdrawn_today, daily_capacity)
                supplied_today = min(withdrawn_today * recovery, demand_today)
                unrestricted_withdrawal = min(water, requested_input)
                if daily_capacity > 0.0:
                    unrestricted_withdrawal = min(
                        unrestricted_withdrawal, daily_capacity
                    )
                unrestricted_supplied_today = min(
                    unrestricted_withdrawal * recovery, demand_today
                )
            else:
                supplied_today = min(available_for_withdrawal, demand_today)
                unrestricted_supplied_today = min(water, demand_today)
                if system.distribution_pump_path:
                    daily_capacity = max(
                        config.system_parameters.pump_capacity_gallons_per_hour, 0.0
                    ) * 24.0
                    if daily_capacity > 0.0:
                        supplied_today = min(supplied_today, daily_capacity)
                        unrestricted_supplied_today = min(
                            unrestricted_supplied_today, daily_capacity
                        )
                withdrawn_today = supplied_today
        met_today = supplied_today >= demand_today
        unmet_today = max(demand_today - supplied_today, 0.0)
        municipal_makeup_today = (
            unmet_today
            if config.system_parameters.municipal_backup_enabled
            and (system.municipal_reaches_end_uses or system.municipal_reaches_booster)
            else 0.0
        )
        system_unmet_today = max(unmet_today - municipal_makeup_today, 0.0)
        reserve_unmet_today = min(
            unmet_today,
            max(unrestricted_supplied_today - supplied_today, 0.0),
        )
        treatment_loss_today = max(withdrawn_today - supplied_today, 0.0)
        pump_flow_today = (
            withdrawn_today
            if system.filtration_path
            else supplied_today if system.distribution_pump_path else 0.0
        )
        sewer_eligible_supplied_today = (
            supplied_today * sewer_eligible_demand_today / demand_today
            if demand_today > 0.0 else 0.0
        )
        water = max(water - withdrawn_today, 0.0)
        water += float(collected.iloc[i])
        overflow_today = max(water - tank_size_gallons, 0.0)
        water = min(max(water, 0.0), tank_size_gallons)

        water_level.append(float(water))
        demand_met.append(bool(met_today))
        usable_water_available.append(float(max(water - minimum_operating_volume, 0.0)))
        operating_reserve_stored.append(float(min(water, minimum_operating_volume)))
        unmet_demand.append(float(unmet_today))
        supplied_demand.append(float(supplied_today))
        sewer_eligible_supplied.append(float(sewer_eligible_supplied_today))
        municipal_makeup.append(float(municipal_makeup_today))
        system_unmet_demand.append(float(system_unmet_today))
        reserve_unmet_demand.append(float(reserve_unmet_today))
        treatment_loss.append(float(treatment_loss_today))
        pump_flow.append(float(pump_flow_today))
        overflow.append(float(overflow_today))

        if met_today:
            reliable_days += 1

    reliability = (reliable_days / len(data)) * 100 if len(data) else 0.0

    result = pd.DataFrame(
        {
            "Date": data["Date"],
            "Precipitation": data["Precipitation"],
            "GrossCollectedGallons": collection["GrossCollectedGallons"],
            "FirstFlushLossGallons": collection["FirstFlushLossGallons"],
            "CollectedGallons": collected,
            "RainfallEventId": collection["RainfallEventId"],
            "RainfallEventStart": collection["RainfallEventStart"],
            "DemandGallons": demand,
            "SewerEligibleDemandGallons": sewer_eligible_demand,
            "DemandMet": demand_met,
            "RainwaterSuppliedGallons": supplied_demand,
            "SewerEligibleRainwaterSuppliedGallons": sewer_eligible_supplied,
            "MinimumOperatingVolumeGallons": minimum_operating_volume,
            "TankCapacityGallons": tank_size_gallons,
            "UsableTankCapacityGallons": tank_size_gallons - minimum_operating_volume,
            "UsableWaterAvailableGallons": usable_water_available,
            "OperatingReserveStoredGallons": operating_reserve_stored,
            "OperatingReserveUnmetDemandGallons": reserve_unmet_demand,
            "UnmetDemandGallons": unmet_demand,
            "MainsMakeupGallons": municipal_makeup,
            "SystemUnmetDemandGallons": system_unmet_demand,
            "FilterLossGallons": treatment_loss,
            "PumpFlowGallons": pump_flow,
            "OverflowGallons": overflow,
            "WaterInTankGallons": water_level,
        }
    ).assign(ReliabilityPercent=reliability)
    if minimum_operating_fraction > 0.0:
        unrestricted = simulate_tank(
            config,
            rainfall_df,
            tank_size_gallons,
            tank_parameters=replace(
                params, minimum_operating_volume_percent=0.0
            ),
            cancel_callback=cancel_callback,
            prepared_inputs=prepared_inputs,
        )
        result["OperatingReserveUnmetDemandGallons"] = np.maximum(
            unrestricted["RainwaterSuppliedGallons"].to_numpy(dtype=float)
            - result["RainwaterSuppliedGallons"].to_numpy(dtype=float),
            0.0,
        )
    return result


def simulate_hourly_tank(
    config: ProjectConfig,
    rainfall_df: pd.DataFrame,
    tank_size_gallons: float,
    cancel_callback: Callable[[], bool] | None = None,
    result_start_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Simulate timing-sensitive demand and rainfall on an hourly timestep.

    Hourly demand timing follows the saved profile. Daily demand timing sums the
    profile for each calendar day and applies the total at 12:00. The source
    profile is never rewritten by this aggregation.

    When ``result_start_date`` is provided, earlier rows still warm up the tank
    state but are omitted from the returned frame.
    """
    if tank_size_gallons <= 0:
        raise ValueError("Tank size must be greater than zero.")
    data = _validate_rainfall(rainfall_df)
    system = compile_builder_system(
        config.system_type, config.system_layout, config.system_connections
    )
    indirect = system.filtration_path or system.booster_storage_path
    component_params = config.system_parameters
    pump_capacity = max(float(component_params.pump_capacity_gallons_per_hour), 0.0)
    filtration_pump_capacity = component_params.transfer_pump_capacity_gallons_per_hour
    filter_recovery = min(max(float(component_params.filter_recovery_percent) / 100.0, 0.0), 1.0)
    booster_capacity = (
        max(float(component_params.booster_tank_size_gallons), 0.0)
        if system.booster_storage_path else 0.0
    )
    booster_fill = min(max(float(component_params.booster_initial_fill_percent) / 100.0, 0.0), 1.0)
    booster_water = booster_capacity * booster_fill
    booster_rainwater = booster_water
    booster_municipal_water = 0.0
    booster_minimum_fraction = _operating_fraction(
        component_params.booster_minimum_operating_volume_percent,
        "Buffer minimum operating level",
    )
    booster_minimum_volume = booster_capacity * booster_minimum_fraction
    booster_refill_level = min(
        max(float(component_params.booster_refill_level_percent) / 100.0, 0.0), 1.0
    )
    booster_refill_target = booster_capacity * booster_refill_level
    refill_active = booster_capacity > 0.0 and _buffer_needs_refill(
        booster_water, booster_refill_target, booster_minimum_volume
    )
    hourly_rainfall = expand_hourly_rainfall(
        data, use_synthetic=config.use_synthetic_hourly_rainfall
    )
    collection = collection_balance_series(config, hourly_rainfall)
    if not system.rain_reaches_primary:
        collection.loc[:, [
            "GrossCollectedGallons", "FirstFlushLossGallons", "CollectedGallons"
        ]] = 0.0
    hourly_precipitation = hourly_rainfall["Precipitation"].to_numpy(
        dtype=float, copy=False
    )
    gross_collected_values = collection["GrossCollectedGallons"].to_numpy(
        dtype=float, copy=False
    )
    first_flush_loss_values = collection["FirstFlushLossGallons"].to_numpy(
        dtype=float, copy=False
    )
    collected_values = collection["CollectedGallons"].to_numpy(
        dtype=float, copy=False
    )
    event_id_values = collection["RainfallEventId"].to_numpy(copy=False)
    event_start_values = collection["RainfallEventStart"].to_numpy(
        dtype=bool, copy=False
    )
    base_daily_demand = pd.Series(
        [_base_daily_demand_for_date(config.demand, date) for date in data["Date"]],
        index=data.index,
    )
    base_daily_demand_values = base_daily_demand.to_numpy(dtype=float, copy=False)
    legacy_sewer_eligible_fraction = (
        min(max(config.financial_parameters.sewer_eligible_percent, 0.0), 100.0) / 100.0
    )
    initial_fill = min(max(config.tank_parameters.initial_fill_percent / 100.0, 0.0), 1.0)
    minimum_operating_fraction = _operating_fraction(
        config.tank_parameters.minimum_operating_volume_percent,
        "Primary minimum operating level",
    )
    minimum_operating_volume = tank_size_gallons * minimum_operating_fraction
    water = tank_size_gallons * initial_fill
    cumulative_overflow = 0.0
    output_start = (
        pd.Timestamp(result_start_date).normalize()
        if result_start_date is not None
        else None
    )
    rows: list[dict[str, object]] = []
    met_hours = 0
    for day_index, date in enumerate(data["Date"]):
        if cancel_callback is not None and day_index % 20 == 0 and cancel_callback():
            raise AnalysisCancelledError("Analysis cancelled by user.")
        timestamp = pd.Timestamp(date)
        schedule = config.demand.hourly_schedule_library.get(
            config.demand.active_hourly_schedule_name,
            config.demand.hourly_weekly_fractions,
        )
        fractions = _schedule_fractions_for_date(schedule, timestamp)
        if not any(fractions):
            fractions = [1.0 / 24.0] * 24
        object_hourly_demands = [0.0] * 24
        sewer_eligible_object_hourly_demands = [0.0] * 24
        for demand_object in config.demand.demand_objects:
            values = _demand_object_hourly_for_date(
                config.demand, demand_object, timestamp
            )
            for object_hour, value in enumerate(values):
                object_hourly_demands[object_hour] += float(value)
                sewer_eligible_object_hourly_demands[object_hour] += (
                    float(value)
                    * _demand_object_sewer_eligible_fraction(
                        demand_object,
                        config.financial_parameters.sewer_eligible_percent,
                    )
                )
        demand_by_hour = [
            max(
                float(base_daily_demand_values[day_index]) * fraction
                + object_hourly_demands[hour],
                0.0,
            )
            for hour, fraction in enumerate(fractions)
        ]
        sewer_eligible_demand_by_hour = [
            min(
                max(
                    float(base_daily_demand_values[day_index])
                    * fraction
                    * legacy_sewer_eligible_fraction
                    + sewer_eligible_object_hourly_demands[hour],
                    0.0,
                ),
                demand_by_hour[hour],
            )
            for hour, fraction in enumerate(fractions)
        ]
        if not config.demand.hourly_schedule_enabled:
            demand_by_hour = [0.0] * 24
            demand_by_hour[12] = sum(
                max(
                    float(base_daily_demand_values[day_index]) * fraction
                    + object_hourly_demands[hour],
                    0.0,
                )
                for hour, fraction in enumerate(fractions)
            )
            sewer_eligible_total = sum(sewer_eligible_demand_by_hour)
            sewer_eligible_demand_by_hour = [0.0] * 24
            sewer_eligible_demand_by_hour[12] = min(
                sewer_eligible_total, demand_by_hour[12]
            )
        for hour, fraction in enumerate(fractions):
            hourly_index = day_index * 24 + hour
            primary_tank_beginning = water
            booster_tank_beginning = booster_water
            overflow_beginning_cumulative = cumulative_overflow
            demand_hour = demand_by_hour[hour]
            sewer_eligible_demand_hour = sewer_eligible_demand_by_hour[hour]
            pump_flow = 0.0
            filter_throughput = 0.0
            filter_loss = 0.0
            mains_makeup = 0.0
            mains_supplied = 0.0
            rainwater_supplied = 0.0
            reserve_unmet = 0.0
            reserve_counterfactual_booster_addition = 0.0
            if indirect and system.primary_reaches_end_uses:
                if booster_capacity > 0.0:
                    if refill_active:
                        booster_space = max(booster_capacity - booster_water, 0.0)
                        delivered_capacity = (
                            filtration_pump_capacity * filter_recovery
                            if filtration_pump_capacity > 0.0
                            else booster_space
                        )
                        requested_delivery = min(booster_space, delivered_capacity)
                        requested_input = (
                            requested_delivery / filter_recovery if filter_recovery > 0.0 else 0.0
                        )
                        available_primary_water = max(water - minimum_operating_volume, 0.0)
                        pump_flow = min(available_primary_water, requested_input)
                        if filtration_pump_capacity > 0.0:
                            pump_flow = min(pump_flow, filtration_pump_capacity)
                        unrestricted_pump_flow = min(water, requested_input)
                        if filtration_pump_capacity > 0.0:
                            unrestricted_pump_flow = min(
                                unrestricted_pump_flow, filtration_pump_capacity
                            )
                        filter_throughput = pump_flow * filter_recovery
                        filter_loss = pump_flow - filter_throughput
                        water = max(water - pump_flow, 0.0)
                        if component_params.municipal_backup_enabled and system.municipal_reaches_booster:
                            mains_makeup = max(requested_delivery - filter_throughput, 0.0)
                        else:
                            reserve_counterfactual_booster_addition = min(
                                max(
                                    (unrestricted_pump_flow - pump_flow)
                                    * filter_recovery,
                                    0.0,
                                ),
                                max(booster_space - filter_throughput, 0.0),
                            )
                        booster_rainwater += filter_throughput
                        booster_municipal_water += mains_makeup
                        booster_water = min(booster_rainwater + booster_municipal_water, booster_capacity)
                        if booster_water >= booster_capacity - 1e-9:
                            refill_active = False
                    total_before_demand = booster_water
                    available_booster_water = max(
                        total_before_demand - booster_minimum_volume, 0.0
                    )
                    total_supplied = min(available_booster_water, demand_hour)
                    counterfactual_total_supplied = min(
                        total_before_demand
                        + reserve_counterfactual_booster_addition,
                        demand_hour,
                    )
                    reserve_unmet = max(
                        counterfactual_total_supplied - total_supplied, 0.0
                    )
                    rainwater_fraction = (
                        booster_rainwater / total_before_demand if total_before_demand > 0.0 else 0.0
                    )
                    rainwater_supplied = total_supplied * rainwater_fraction
                    mains_supplied = total_supplied - rainwater_supplied
                    booster_rainwater = max(booster_rainwater - rainwater_supplied, 0.0)
                    booster_municipal_water = max(booster_municipal_water - mains_supplied, 0.0)
                    booster_water = booster_rainwater + booster_municipal_water
                    if _buffer_needs_refill(
                        booster_water,
                        booster_refill_target,
                        booster_minimum_volume,
                    ):
                        refill_active = True
                else:
                    requested_input = demand_hour / filter_recovery if filter_recovery > 0.0 else 0.0
                    available_primary_water = max(water - minimum_operating_volume, 0.0)
                    pump_flow = min(available_primary_water, requested_input)
                    if filtration_pump_capacity > 0.0:
                        pump_flow = min(pump_flow, filtration_pump_capacity)
                    unrestricted_pump_flow = min(water, requested_input)
                    if filtration_pump_capacity > 0.0:
                        unrestricted_pump_flow = min(
                            unrestricted_pump_flow, filtration_pump_capacity
                        )
                    filter_throughput = pump_flow * filter_recovery
                    filter_loss = pump_flow - filter_throughput
                    water = max(water - pump_flow, 0.0)
                    rainwater_supplied = min(filter_throughput, demand_hour)
                    reserve_unmet = max(
                        min(
                            unrestricted_pump_flow * filter_recovery,
                            demand_hour,
                        )
                        - rainwater_supplied,
                        0.0,
                    )
            elif system.primary_reaches_end_uses:
                available_primary_water = max(water - minimum_operating_volume, 0.0)
                rainwater_supplied = min(available_primary_water, demand_hour)
                unrestricted_rainwater_supplied = min(water, demand_hour)
                if system.distribution_pump_path and pump_capacity > 0.0:
                    rainwater_supplied = min(rainwater_supplied, pump_capacity)
                    unrestricted_rainwater_supplied = min(
                        unrestricted_rainwater_supplied, pump_capacity
                    )
                reserve_unmet = max(
                    unrestricted_rainwater_supplied - rainwater_supplied, 0.0
                )
                pump_flow = rainwater_supplied
                water = max(water - rainwater_supplied, 0.0)
            met = rainwater_supplied >= demand_hour
            unmet = max(demand_hour - rainwater_supplied, 0.0)
            reserve_unmet = min(reserve_unmet, unmet)
            if not (indirect and booster_capacity > 0.0):
                mains_makeup = (
                    unmet
                    if component_params.municipal_backup_enabled and system.municipal_reaches_end_uses
                    else 0.0
                )
                mains_supplied = mains_makeup
                system_unmet = max(unmet - mains_makeup, 0.0)
            else:
                system_unmet = max(demand_hour - rainwater_supplied - mains_supplied, 0.0)
            sewer_eligible_rainwater_supplied = (
                rainwater_supplied * sewer_eligible_demand_hour / demand_hour
                if demand_hour > 0.0 else 0.0
            )
            collected_hour = float(collected_values[hourly_index])
            gross_collected_hour = float(gross_collected_values[hourly_index])
            first_flush_loss_hour = float(first_flush_loss_values[hourly_index])
            water += collected_hour
            overflow = max(water - tank_size_gallons, 0.0)
            water = min(max(water, 0.0), tank_size_gallons)
            cumulative_overflow += overflow
            include_row = output_start is None or timestamp.normalize() >= output_start
            if not include_row:
                continue
            met_hours += int(met)
            rows.append(
                {
                    "Date": pd.Timestamp(date) + pd.Timedelta(hours=hour),
                    "SystemType": system.display_type,
                    "Precipitation": float(hourly_precipitation[hourly_index]),
                    "GrossCollectedGallons": gross_collected_hour,
                    "FirstFlushLossGallons": first_flush_loss_hour,
                    "CollectedGallons": collected_hour,
                    "RainfallEventId": event_id_values[hourly_index],
                    "RainfallEventStart": bool(event_start_values[hourly_index]),
                    "DemandGallons": demand_hour,
                    "SewerEligibleDemandGallons": sewer_eligible_demand_hour,
                    "DemandMet": met,
                    "RainwaterSuppliedGallons": rainwater_supplied,
                    "SewerEligibleRainwaterSuppliedGallons": sewer_eligible_rainwater_supplied,
                    "UnmetDemandGallons": unmet,
                    "SystemUnmetDemandGallons": system_unmet,
                    "OperatingReserveUnmetDemandGallons": reserve_unmet,
                    "MainsMakeupGallons": mains_makeup,
                    "MainsSuppliedGallons": mains_supplied,
                    "PumpFlowGallons": pump_flow,
                    "FilterThroughputGallons": filter_throughput,
                    "FilterLossGallons": filter_loss,
                    "PrimaryTankBeginningGallons": primary_tank_beginning,
                    "BoosterTankBeginningGallons": booster_tank_beginning,
                    "BoosterTankGallons": booster_water,
                    "BoosterTankCapacityGallons": booster_capacity,
                    "BoosterMinimumOperatingVolumeGallons": booster_minimum_volume,
                    "BoosterUsableTankCapacityGallons": (
                        booster_capacity - booster_minimum_volume
                    ),
                    "BoosterUsableWaterAvailableGallons": max(
                        booster_water - booster_minimum_volume, 0.0
                    ),
                    "BoosterOperatingReserveStoredGallons": min(
                        booster_water, booster_minimum_volume
                    ),
                    "BoosterRefillActive": refill_active,
                    "OverflowGallons": overflow,
                    "OverflowBeginningCumulativeGallons": overflow_beginning_cumulative,
                    "CumulativeOverflowGallons": cumulative_overflow,
                    "WaterInTankGallons": water,
                    "TankCapacityGallons": tank_size_gallons,
                    "MinimumOperatingVolumeGallons": minimum_operating_volume,
                    "UsableTankCapacityGallons": (
                        tank_size_gallons - minimum_operating_volume
                    ),
                    "UsableWaterAvailableGallons": max(water - minimum_operating_volume, 0.0),
                    "OperatingReserveStoredGallons": min(
                        water, minimum_operating_volume
                    ),
                }
            )
    reliability = met_hours / len(rows) * 100.0 if rows else 0.0
    result = pd.DataFrame(rows).assign(ReliabilityPercent=reliability)
    if minimum_operating_fraction > 0.0 or booster_minimum_fraction > 0.0:
        unrestricted_config = deepcopy(config)
        unrestricted_config.tank_parameters.minimum_operating_volume_percent = 0.0
        unrestricted_config.system_parameters.booster_minimum_operating_volume_percent = 0.0
        unrestricted = simulate_hourly_tank(
            unrestricted_config,
            rainfall_df,
            tank_size_gallons,
            cancel_callback=cancel_callback,
            result_start_date=result_start_date,
        )
        result["OperatingReserveUnmetDemandGallons"] = np.maximum(
            unrestricted["RainwaterSuppliedGallons"].to_numpy(dtype=float)
            - result["RainwaterSuppliedGallons"].to_numpy(dtype=float),
            0.0,
        )
    return result


def _daily_curve_from_prepared(
    config: ProjectConfig,
    prepared: PreparedDailyInputs,
    tank_sizes: list[float],
    tank_parameters: TankParameters,
    cancel_callback: Callable[[], bool] | None = None,
) -> pd.DataFrame:
    """Simulate every daily curve candidate together without timestep frames."""
    capacities = np.asarray(tank_sizes, dtype=np.float64)
    if np.any(capacities <= 0.0):
        raise ValueError("Tank size must be greater than zero.")
    candidate_count = capacities.size
    system = compile_builder_system(
        config.system_type, config.system_layout, config.system_connections
    )
    initial_fill = min(max(tank_parameters.initial_fill_percent / 100.0, 0.0), 1.0)
    minimum_fraction = _operating_fraction(
        tank_parameters.minimum_operating_volume_percent,
        "Primary minimum operating level",
    )
    minimum_volumes = capacities * minimum_fraction
    water = capacities * initial_fill
    reliable_days = np.zeros(candidate_count, dtype=np.int64)
    supplied_total = np.zeros(candidate_count, dtype=np.float64)
    sewer_supplied_total = np.zeros(candidate_count, dtype=np.float64)
    unmet_total = np.zeros(candidate_count, dtype=np.float64)
    makeup_total = np.zeros(candidate_count, dtype=np.float64)
    system_unmet_total = np.zeros(candidate_count, dtype=np.float64)
    reserve_unmet_total = np.zeros(candidate_count, dtype=np.float64)
    overflow_total = np.zeros(candidate_count, dtype=np.float64)
    treatment_loss_total = np.zeros(candidate_count, dtype=np.float64)
    pump_total = np.zeros(candidate_count, dtype=np.float64)
    recovery = min(
        max(config.system_parameters.filter_recovery_percent / 100.0, 0.0), 1.0
    )
    transfer_capacity = max(
        config.system_parameters.transfer_pump_capacity_gallons_per_hour, 0.0
    ) * 24.0
    distribution_capacity = max(
        config.system_parameters.pump_capacity_gallons_per_hour, 0.0
    ) * 24.0
    collected = (
        prepared.collected_gallons
        if system.rain_reaches_primary
        else np.zeros_like(prepared.collected_gallons)
    )

    for index, demand_value in enumerate(prepared.demand_gallons):
        if cancel_callback is not None and index % 100 == 0 and cancel_callback():
            raise AnalysisCancelledError("Analysis cancelled by user.")
        demand_today = max(float(demand_value), 0.0)
        sewer_demand_today = min(
            max(float(prepared.sewer_eligible_demand_gallons[index]), 0.0),
            demand_today,
        )
        available = np.maximum(water - minimum_volumes, 0.0)
        supplied = np.zeros(candidate_count, dtype=np.float64)
        unrestricted_supplied = np.zeros(candidate_count, dtype=np.float64)
        withdrawn = np.zeros(candidate_count, dtype=np.float64)
        if system.primary_reaches_end_uses:
            if system.filtration_path:
                requested = demand_today / recovery if recovery > 0.0 else 0.0
                withdrawn = np.minimum(available, requested)
                if transfer_capacity > 0.0:
                    withdrawn = np.minimum(withdrawn, transfer_capacity)
                supplied = np.minimum(withdrawn * recovery, demand_today)
                unrestricted_withdrawal = np.minimum(water, requested)
                if transfer_capacity > 0.0:
                    unrestricted_withdrawal = np.minimum(
                        unrestricted_withdrawal, transfer_capacity
                    )
                unrestricted_supplied = np.minimum(
                    unrestricted_withdrawal * recovery, demand_today
                )
            else:
                supplied = np.minimum(available, demand_today)
                unrestricted_supplied = np.minimum(water, demand_today)
                if system.distribution_pump_path and distribution_capacity > 0.0:
                    supplied = np.minimum(supplied, distribution_capacity)
                    unrestricted_supplied = np.minimum(
                        unrestricted_supplied, distribution_capacity
                    )
                withdrawn = supplied
        unmet = np.maximum(demand_today - supplied, 0.0)
        makeup = (
            unmet
            if config.system_parameters.municipal_backup_enabled
            and (system.municipal_reaches_end_uses or system.municipal_reaches_booster)
            else np.zeros(candidate_count, dtype=np.float64)
        )
        system_unmet = np.maximum(unmet - makeup, 0.0)
        reserve_unmet = np.minimum(
            unmet, np.maximum(unrestricted_supplied - supplied, 0.0)
        )
        treatment_loss = np.maximum(withdrawn - supplied, 0.0)
        pump = (
            withdrawn
            if system.filtration_path
            else supplied
            if system.distribution_pump_path
            else np.zeros(candidate_count, dtype=np.float64)
        )
        sewer_supplied = (
            supplied * sewer_demand_today / demand_today
            if demand_today > 0.0
            else np.zeros(candidate_count, dtype=np.float64)
        )
        water = np.maximum(water - withdrawn, 0.0) + float(collected[index])
        overflow = np.maximum(water - capacities, 0.0)
        water = np.minimum(np.maximum(water, 0.0), capacities)

        reliable_days += supplied >= demand_today
        supplied_total += supplied
        sewer_supplied_total += sewer_supplied
        unmet_total += unmet
        makeup_total += makeup
        system_unmet_total += system_unmet
        reserve_unmet_total += reserve_unmet
        overflow_total += overflow
        treatment_loss_total += treatment_loss
        pump_total += pump

    day_count = prepared.demand_gallons.size
    year_count = prepared.year_count
    first_flush_total = (
        float(prepared.first_flush_loss_gallons.sum())
        if system.rain_reaches_primary
        else 0.0
    )
    result = pd.DataFrame(
        {
            "TankSizeGallons": capacities,
            "ReliabilityPercent": (
                reliable_days / day_count * 100.0
                if day_count
                else np.zeros(candidate_count, dtype=np.float64)
            ),
            "TotalDemandGallons": float(prepared.demand_gallons.sum()),
            "RainwaterSuppliedGallons": supplied_total,
            "AverageAnnualRainwaterSuppliedGallons": supplied_total / year_count,
            "SewerEligibleRainwaterSuppliedGallons": sewer_supplied_total,
            "AverageAnnualSewerEligibleRainwaterSuppliedGallons": (
                sewer_supplied_total / year_count
            ),
            "AverageAnnualPumpFlowGallons": pump_total / year_count,
            "UnmetDemandGallons": unmet_total,
            "MunicipalMakeupGallons": makeup_total,
            "SystemUnmetDemandGallons": system_unmet_total,
            "OperatingReserveUnmetDemandGallons": reserve_unmet_total,
            "OverflowGallons": overflow_total,
            "FirstFlushLossGallons": first_flush_total,
            "TreatmentLossGallons": treatment_loss_total,
            "FinalStorageGallons": water,
            "FinalUsableWaterAvailableGallons": np.maximum(
                water - minimum_volumes, 0.0
            ),
        }
    )
    if minimum_fraction > 0.0:
        unrestricted = _daily_curve_from_prepared(
            config,
            prepared,
            tank_sizes,
            replace(tank_parameters, minimum_operating_volume_percent=0.0),
            cancel_callback=cancel_callback,
        )
        result["OperatingReserveUnmetDemandGallons"] = np.maximum(
            unrestricted["RainwaterSuppliedGallons"].to_numpy(dtype=float)
            - result["RainwaterSuppliedGallons"].to_numpy(dtype=float),
            0.0,
        )
    return result


def reliability_curve(
    config: ProjectConfig,
    rainfall_df: pd.DataFrame,
    tank_sizes_gallons: Iterable[float],
    tank_parameters: TankParameters | None = None,
    progress_callback: Callable[[int, int, float], None] | None = None,
    cancel_callback: Callable[[], bool] | None = None,
    prepared_inputs: PreparedDailyInputs | None = None,
) -> pd.DataFrame:
    tank_sizes = list(tank_sizes_gallons)
    prepared = prepared_inputs or prepare_daily_inputs(config, rainfall_df)
    curve = _daily_curve_from_prepared(
        config,
        prepared,
        tank_sizes,
        tank_parameters or config.tank_parameters,
        cancel_callback=cancel_callback,
    )
    candidate_count = len(tank_sizes)
    for index, tank_size in enumerate(tank_sizes, start=1):
        if progress_callback is not None:
            progress_callback(index, candidate_count, float(tank_size))
    return curve
