from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
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
)
from .rainfall import expand_hourly_rainfall
from .system_model import compile_builder_system

GAL_PER_CUBIC_FOOT = 7.48052


class AnalysisCancelledError(RuntimeError):
    """Raised when a running simulation is cooperatively cancelled."""


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
    diversion_depths = np.array(
        [max(float(s.first_flush_depth_inches), 0.0) for s in config.surfaces], dtype=float
    )
    diversion_allowances = (
        areas * coeffs * diversion_depths / 12.0 * GAL_PER_CUBIC_FOOT
    )
    antecedent = pd.Timedelta(days=max(float(config.first_flush_antecedent_dry_days), 0.0))
    last_wet_time: pd.Timestamp | None = None
    event_id = 0
    gross_values: list[float] = []
    loss_values: list[float] = []
    net_values: list[float] = []
    event_ids: list[int | None] = []
    event_starts: list[bool] = []
    precip = data["Precipitation"].to_numpy(dtype=float)
    for index, precipitation in enumerate(precip):
        timestamp = pd.Timestamp(data["Date"].iloc[index])
        wet = precipitation > 0.0
        starts_event = bool(
            wet and (last_wet_time is None or timestamp - last_wet_time > antecedent)
        )
        if starts_event:
            event_id += 1
        surface_runoff = areas * coeffs * max(float(precipitation), 0.0) / 12.0 * GAL_PER_CUBIC_FOOT
        surface_loss = (
            np.minimum(surface_runoff, diversion_allowances)
            if starts_event
            else np.zeros_like(areas)
        )
        gross = float(surface_runoff.sum())
        loss = float(surface_loss.sum())
        gross_values.append(gross)
        loss_values.append(loss)
        net_values.append(max(gross - loss, 0.0))
        event_ids.append(event_id if wet else None)
        event_starts.append(starts_event)
        if wet:
            last_wet_time = timestamp
    return pd.DataFrame(
        {
            "GrossCollectedGallons": gross_values,
            "FirstFlushLossGallons": loss_values,
            "CollectedGallons": net_values,
            "RainfallEventId": pd.array(event_ids, dtype="Int64"),
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
    """Precompute candidate-independent hourly demand, collection, and year arrays."""
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
        demand_values[start:start + 24] = legacy_daily * fraction_values + object_demands
        sewer_eligible_demand_values[start:start + 24] = (
            legacy_daily
            * min(max(config.financial_parameters.sewer_eligible_percent, 0.0), 100.0)
            / 100.0
            * fraction_values
            + sewer_eligible_object_demands
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
    refill_target = booster_capacity * min(max(float(params.booster_refill_level_percent) / 100.0, 0.0), 1.0)
    refill_active = booster_capacity > 0.0 and booster_water < refill_target
    water = tank_size_gallons * min(max(config.tank_parameters.initial_fill_percent / 100.0, 0.0), 1.0)
    minimum_volume = tank_size_gallons * min(
        max(config.tank_parameters.minimum_operating_volume_percent / 100.0, 0.0), 1.0
    )
    annual_supplied = np.zeros(prepared.year_count, dtype=np.float64)
    annual_sewer_eligible_supplied = np.zeros(prepared.year_count, dtype=np.float64)
    annual_makeup = np.zeros(prepared.year_count, dtype=np.float64)
    annual_overflow = np.zeros(prepared.year_count, dtype=np.float64)
    annual_pump = np.zeros(prepared.year_count, dtype=np.float64)
    met_hours = 0
    for index in range(prepared.demand_gallons.size):
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
            total_supplied = min(total_before_demand, demand)
            rainwater_fraction = booster_rainwater / total_before_demand if total_before_demand > 0.0 else 0.0
            rainwater_supplied = total_supplied * rainwater_fraction
            mains_supplied = total_supplied - rainwater_supplied
            booster_rainwater = max(booster_rainwater - rainwater_supplied, 0.0)
            booster_municipal = max(booster_municipal - mains_supplied, 0.0)
            booster_water = booster_rainwater + booster_municipal
            if booster_water < refill_target:
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
) -> pd.DataFrame:
    if tank_size_gallons <= 0:
        raise ValueError("Tank size must be greater than zero.")

    params = tank_parameters or config.tank_parameters
    data = _validate_rainfall(rainfall_df)
    system = compile_builder_system(
        config.system_type, config.system_layout, config.system_connections
    )
    collection = collection_balance_series(config, data)
    if not system.rain_reaches_primary:
        collection.loc[:, [
            "GrossCollectedGallons", "FirstFlushLossGallons", "CollectedGallons"
        ]] = 0.0
    collected = collection["CollectedGallons"]
    demand = demand_series(config, data)
    sewer_eligible_demand = sewer_eligible_demand_series(config, data)

    initial_fill = min(max(params.initial_fill_percent / 100.0, 0.0), 1.0)
    minimum_operating_fraction = min(
        max(params.minimum_operating_volume_percent / 100.0, 0.0), 1.0
    )
    minimum_operating_volume = tank_size_gallons * minimum_operating_fraction
    water_level: list[float] = []
    demand_met: list[bool] = []
    usable_water_available: list[float] = []
    unmet_demand: list[float] = []
    supplied_demand: list[float] = []
    sewer_eligible_supplied: list[float] = []
    municipal_makeup: list[float] = []
    system_unmet_demand: list[float] = []
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
            else:
                supplied_today = min(available_for_withdrawal, demand_today)
                if system.distribution_pump_path:
                    daily_capacity = max(
                        config.system_parameters.pump_capacity_gallons_per_hour, 0.0
                    ) * 24.0
                    if daily_capacity > 0.0:
                        supplied_today = min(supplied_today, daily_capacity)
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
        unmet_demand.append(float(unmet_today))
        supplied_demand.append(float(supplied_today))
        sewer_eligible_supplied.append(float(sewer_eligible_supplied_today))
        municipal_makeup.append(float(municipal_makeup_today))
        system_unmet_demand.append(float(system_unmet_today))
        treatment_loss.append(float(treatment_loss_today))
        pump_flow.append(float(pump_flow_today))
        overflow.append(float(overflow_today))

        if met_today:
            reliable_days += 1

    reliability = (reliable_days / len(data)) * 100 if len(data) else 0.0

    return pd.DataFrame(
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
            "UsableWaterAvailableGallons": usable_water_available,
            "UnmetDemandGallons": unmet_demand,
            "MainsMakeupGallons": municipal_makeup,
            "SystemUnmetDemandGallons": system_unmet_demand,
            "FilterLossGallons": treatment_loss,
            "PumpFlowGallons": pump_flow,
            "OverflowGallons": overflow,
            "WaterInTankGallons": water_level,
        }
    ).assign(ReliabilityPercent=reliability)


def simulate_hourly_tank(
    config: ProjectConfig,
    rainfall_df: pd.DataFrame,
    tank_size_gallons: float,
    cancel_callback: Callable[[], bool] | None = None,
    result_start_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Simulate hourly demand using synthetic profiles or the 23:00 fallback.

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
    booster_refill_level = min(
        max(float(component_params.booster_refill_level_percent) / 100.0, 0.0), 1.0
    )
    booster_refill_target = booster_capacity * booster_refill_level
    refill_active = booster_capacity > 0.0 and booster_water < booster_refill_target
    hourly_rainfall = expand_hourly_rainfall(
        data, use_synthetic=config.use_synthetic_hourly_rainfall
    )
    collection = collection_balance_series(config, hourly_rainfall)
    if not system.rain_reaches_primary:
        collection.loc[:, [
            "GrossCollectedGallons", "FirstFlushLossGallons", "CollectedGallons"
        ]] = 0.0
    base_daily_demand = pd.Series(
        [_base_daily_demand_for_date(config.demand, date) for date in data["Date"]],
        index=data.index,
    )
    legacy_sewer_eligible_fraction = (
        min(max(config.financial_parameters.sewer_eligible_percent, 0.0), 100.0) / 100.0
    )
    initial_fill = min(max(config.tank_parameters.initial_fill_percent / 100.0, 0.0), 1.0)
    minimum_operating_fraction = min(
        max(config.tank_parameters.minimum_operating_volume_percent / 100.0, 0.0), 1.0
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
        for hour, fraction in enumerate(fractions):
            hourly_index = day_index * 24 + hour
            primary_tank_beginning = water
            booster_tank_beginning = booster_water
            overflow_beginning_cumulative = cumulative_overflow
            demand_hour = max(
                float(base_daily_demand.iloc[day_index]) * fraction + object_hourly_demands[hour],
                0.0,
            )
            sewer_eligible_demand_hour = min(
                max(
                    float(base_daily_demand.iloc[day_index])
                    * fraction
                    * legacy_sewer_eligible_fraction
                    + sewer_eligible_object_hourly_demands[hour],
                    0.0,
                ),
                demand_hour,
            )
            pump_flow = 0.0
            filter_throughput = 0.0
            filter_loss = 0.0
            mains_makeup = 0.0
            mains_supplied = 0.0
            rainwater_supplied = 0.0
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
                        filter_throughput = pump_flow * filter_recovery
                        filter_loss = pump_flow - filter_throughput
                        water = max(water - pump_flow, 0.0)
                        if component_params.municipal_backup_enabled and system.municipal_reaches_booster:
                            mains_makeup = max(requested_delivery - filter_throughput, 0.0)
                        booster_rainwater += filter_throughput
                        booster_municipal_water += mains_makeup
                        booster_water = min(booster_rainwater + booster_municipal_water, booster_capacity)
                        if booster_water >= booster_capacity - 1e-9:
                            refill_active = False
                    total_before_demand = booster_water
                    total_supplied = min(total_before_demand, demand_hour)
                    rainwater_fraction = (
                        booster_rainwater / total_before_demand if total_before_demand > 0.0 else 0.0
                    )
                    rainwater_supplied = total_supplied * rainwater_fraction
                    mains_supplied = total_supplied - rainwater_supplied
                    booster_rainwater = max(booster_rainwater - rainwater_supplied, 0.0)
                    booster_municipal_water = max(booster_municipal_water - mains_supplied, 0.0)
                    booster_water = booster_rainwater + booster_municipal_water
                    if booster_water < booster_refill_target:
                        refill_active = True
                else:
                    requested_input = demand_hour / filter_recovery if filter_recovery > 0.0 else 0.0
                    available_primary_water = max(water - minimum_operating_volume, 0.0)
                    pump_flow = min(available_primary_water, requested_input)
                    if filtration_pump_capacity > 0.0:
                        pump_flow = min(pump_flow, filtration_pump_capacity)
                    filter_throughput = pump_flow * filter_recovery
                    filter_loss = pump_flow - filter_throughput
                    water = max(water - pump_flow, 0.0)
                    rainwater_supplied = min(filter_throughput, demand_hour)
            elif system.primary_reaches_end_uses:
                available_primary_water = max(water - minimum_operating_volume, 0.0)
                rainwater_supplied = min(available_primary_water, demand_hour)
                if system.distribution_pump_path and pump_capacity > 0.0:
                    rainwater_supplied = min(rainwater_supplied, pump_capacity)
                pump_flow = rainwater_supplied
                water = max(water - rainwater_supplied, 0.0)
            met = rainwater_supplied >= demand_hour
            unmet = max(demand_hour - rainwater_supplied, 0.0)
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
            collected_hour = float(collection["CollectedGallons"].iloc[hourly_index])
            gross_collected_hour = float(
                collection["GrossCollectedGallons"].iloc[hourly_index]
            )
            first_flush_loss_hour = float(
                collection["FirstFlushLossGallons"].iloc[hourly_index]
            )
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
                    "Precipitation": float(
                        hourly_rainfall["Precipitation"].iloc[hourly_index]
                    ),
                    "GrossCollectedGallons": gross_collected_hour,
                    "FirstFlushLossGallons": first_flush_loss_hour,
                    "CollectedGallons": collected_hour,
                    "RainfallEventId": collection["RainfallEventId"].iloc[hourly_index],
                    "RainfallEventStart": bool(
                        collection["RainfallEventStart"].iloc[hourly_index]
                    ),
                    "DemandGallons": demand_hour,
                    "SewerEligibleDemandGallons": sewer_eligible_demand_hour,
                    "DemandMet": met,
                    "RainwaterSuppliedGallons": rainwater_supplied,
                    "SewerEligibleRainwaterSuppliedGallons": sewer_eligible_rainwater_supplied,
                    "UnmetDemandGallons": unmet,
                    "SystemUnmetDemandGallons": system_unmet,
                    "MainsMakeupGallons": mains_makeup,
                    "MainsSuppliedGallons": mains_supplied,
                    "PumpFlowGallons": pump_flow,
                    "FilterThroughputGallons": filter_throughput,
                    "FilterLossGallons": filter_loss,
                    "PrimaryTankBeginningGallons": primary_tank_beginning,
                    "BoosterTankBeginningGallons": booster_tank_beginning,
                    "BoosterTankGallons": booster_water,
                    "BoosterRefillActive": refill_active,
                    "OverflowGallons": overflow,
                    "OverflowBeginningCumulativeGallons": overflow_beginning_cumulative,
                    "CumulativeOverflowGallons": cumulative_overflow,
                    "WaterInTankGallons": water,
                    "MinimumOperatingVolumeGallons": minimum_operating_volume,
                    "UsableWaterAvailableGallons": max(water - minimum_operating_volume, 0.0),
                }
            )
    reliability = met_hours / len(rows) * 100.0 if rows else 0.0
    return pd.DataFrame(rows).assign(ReliabilityPercent=reliability)


def reliability_curve(
    config: ProjectConfig,
    rainfall_df: pd.DataFrame,
    tank_sizes_gallons: Iterable[float],
    tank_parameters: TankParameters | None = None,
    progress_callback: Callable[[int, int, float], None] | None = None,
    cancel_callback: Callable[[], bool] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    tank_sizes = list(tank_sizes_gallons)
    candidate_count = len(tank_sizes)
    for index, tank_size in enumerate(tank_sizes, start=1):
        if cancel_callback is not None and cancel_callback():
            raise AnalysisCancelledError("Analysis cancelled by user.")
        result = simulate_tank(
            config,
            rainfall_df,
            tank_size,
            tank_parameters=tank_parameters,
            cancel_callback=cancel_callback,
        )
        reliability = float(result["ReliabilityPercent"].iloc[0]) if not result.empty else 0.0
        dates = pd.to_datetime(result.get("Date", pd.Series(dtype="datetime64[ns]")), errors="coerce")
        year_count = max(int(dates.dropna().dt.year.nunique()), 1)

        def column_total(column: str) -> float:
            return float(pd.to_numeric(result.get(column, pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())

        supplied = column_total("RainwaterSuppliedGallons")
        sewer_eligible_supplied = column_total("SewerEligibleRainwaterSuppliedGallons")
        rows.append({
            "TankSizeGallons": float(tank_size),
            "ReliabilityPercent": reliability,
            "TotalDemandGallons": column_total("DemandGallons"),
            "RainwaterSuppliedGallons": supplied,
            "AverageAnnualRainwaterSuppliedGallons": supplied / year_count,
            "SewerEligibleRainwaterSuppliedGallons": sewer_eligible_supplied,
            "AverageAnnualSewerEligibleRainwaterSuppliedGallons": (
                sewer_eligible_supplied / year_count
            ),
            "AverageAnnualPumpFlowGallons": column_total("PumpFlowGallons") / year_count,
            "UnmetDemandGallons": column_total("UnmetDemandGallons"),
            "MunicipalMakeupGallons": column_total("MainsMakeupGallons"),
            "SystemUnmetDemandGallons": column_total("SystemUnmetDemandGallons"),
            "OverflowGallons": column_total("OverflowGallons"),
            "FirstFlushLossGallons": column_total("FirstFlushLossGallons"),
            "TreatmentLossGallons": column_total("FilterLossGallons"),
            "FinalStorageGallons": (
                float(result["WaterInTankGallons"].iloc[-1]) if not result.empty else 0.0
            ),
        })
        if progress_callback is not None:
            progress_callback(index, candidate_count, float(tank_size))

    return pd.DataFrame(rows)
