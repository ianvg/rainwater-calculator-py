from __future__ import annotations

from calendar import monthrange
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from .models import DemandProfile, MONTH_KEYS, ProjectConfig, TankParameters, WEEKDAY_KEYS
from .system_model import build_custom_system, build_system_template

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


def _demand_object_daily_for_date(demand: DemandProfile, date: pd.Timestamp) -> float:
    total = 0.0
    for demand_object in demand.demand_objects:
        schedule = demand.hourly_schedule_library.get(demand_object.schedule_name)
        if schedule is None:
            continue
        day_key = WEEKDAY_KEYS[date.weekday()]
        multipliers = [min(max(float(value), 0.0), 1.0) for value in schedule.get(day_key, [])[:24]]
        total += (
            max(float(demand_object.instantaneous_demand_gallons_per_minute), 0.0)
            * 60.0
            * sum(multipliers)
        )
    return total


def _daily_demand_for_date(demand: DemandProfile, date: pd.Timestamp) -> float:
    return _base_daily_demand_for_date(demand, date) + _demand_object_daily_for_date(demand, date)


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
    cancel_callback: Callable[[], bool] | None = None,
) -> pd.DataFrame:
    if tank_size_gallons <= 0:
        raise ValueError("Tank size must be greater than zero.")
    if config.system_type == "Custom system":
        hourly = simulate_hourly_tank(
            config,
            rainfall_df,
            tank_size_gallons,
            cancel_callback=cancel_callback,
        )
        if hourly.empty:
            return pd.DataFrame(
                columns=[
                    "Date", "Precipitation", "CollectedGallons", "DemandGallons",
                    "DemandMet", "ReserveTargetMet", "UnmetDemandGallons",
                    "OverflowGallons", "WaterInTankGallons", "ReliabilityPercent",
                ]
            )
        daily = hourly.assign(Day=pd.to_datetime(hourly["Date"]).dt.normalize()).groupby(
            "Day", sort=True
        ).agg(
            CollectedGallons=("CollectedGallons", "sum"),
            DemandGallons=("DemandGallons", "sum"),
            UnmetDemandGallons=("UnmetDemandGallons", "sum"),
            OverflowGallons=("OverflowGallons", "sum"),
            WaterInTankGallons=("WaterInTankGallons", "last"),
        ).reset_index().rename(columns={"Day": "Date"})
        validated_rainfall = _validate_rainfall(rainfall_df)
        rainfall = validated_rainfall.set_index(
            pd.to_datetime(validated_rainfall["Date"]).dt.normalize()
        )["Precipitation"]
        daily["Precipitation"] = daily["Date"].map(rainfall).fillna(0.0)
        daily["DemandMet"] = daily["UnmetDemandGallons"] <= 1e-9
        daily["ReserveTargetMet"] = daily["DemandMet"]
        reliability = float(daily["DemandMet"].mean() * 100.0) if not daily.empty else 0.0
        return daily[
            [
                "Date", "Precipitation", "CollectedGallons", "DemandGallons", "DemandMet",
                "ReserveTargetMet", "UnmetDemandGallons", "OverflowGallons",
                "WaterInTankGallons",
            ]
        ].assign(ReliabilityPercent=reliability)

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
        if cancel_callback is not None and i % 100 == 0 and cancel_callback():
            raise AnalysisCancelledError("Analysis cancelled by user.")
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


def simulate_hourly_tank(
    config: ProjectConfig,
    rainfall_df: pd.DataFrame,
    tank_size_gallons: float,
    cancel_callback: Callable[[], bool] | None = None,
) -> pd.DataFrame:
    """Simulate hourly demand; each day's rainfall enters after hour 23."""
    if tank_size_gallons <= 0:
        raise ValueError("Tank size must be greater than zero.")
    data = _validate_rainfall(rainfall_df)
    system = (
        build_custom_system(config.system_layout, config.system_connections)
        if config.system_type == "Custom system"
        else build_system_template(config.system_type)
    )
    custom_path = str(
        system.components.get("__metadata__", None).properties.get("service_path", "")
        if "__metadata__" in system.components else ""
    ).split(",")
    indirect = system.system_type == "Indirect system" or any(
        kind in custom_path for kind in ("filtration_pump", "filtration_system", "booster_tank")
    )
    has_filter = system.system_type != "Custom system" or "filtration_system" in custom_path
    has_filtration_pump = system.system_type != "Custom system" or "filtration_pump" in custom_path
    has_booster = system.system_type != "Custom system" or "booster_tank" in custom_path
    component_params = config.system_parameters
    pump_capacity = max(float(component_params.pump_capacity_gallons_per_hour), 0.0)
    if system.system_type == "Custom system" and "booster_pump" not in custom_path:
        pump_capacity = 0.0
    filtration_pump_capacity = (
        max(float(component_params.filtration_pump_capacity_gallons_per_hour), 0.0)
        if has_filtration_pump else 0.0
    )
    filter_recovery = (
        min(max(float(component_params.filter_recovery_percent) / 100.0, 0.0), 1.0)
        if has_filter else 1.0
    )
    booster_capacity = (
        max(float(component_params.booster_tank_size_gallons), 0.0)
        if indirect and has_booster else 0.0
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
    collected = collected_water_series(config, data)
    base_daily_demand = pd.Series(
        [_base_daily_demand_for_date(config.demand, date) for date in data["Date"]],
        index=data.index,
    )
    initial_fill = min(max(config.tank_parameters.initial_fill_percent / 100.0, 0.0), 1.0)
    water = tank_size_gallons * initial_fill
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
        for demand_object in config.demand.demand_objects:
            object_schedule = config.demand.hourly_schedule_library.get(demand_object.schedule_name)
            if object_schedule is None:
                continue
            day_key = WEEKDAY_KEYS[timestamp.weekday()]
            object_multipliers = [
                min(max(float(value), 0.0), 1.0)
                for value in object_schedule.get(day_key, [])[:24]
            ]
            object_multipliers.extend([0.0] * (24 - len(object_multipliers)))
            object_flow = max(float(demand_object.instantaneous_demand_gallons_per_minute), 0.0)
            for object_hour, object_multiplier in enumerate(object_multipliers):
                object_hourly_demands[object_hour] += object_flow * object_multiplier * 60.0
        for hour, fraction in enumerate(fractions):
            stored_before = water + booster_water
            demand_hour = max(
                float(base_daily_demand.iloc[day_index]) * fraction + object_hourly_demands[hour],
                0.0,
            )
            pump_flow = 0.0
            filter_throughput = 0.0
            filter_loss = 0.0
            mains_makeup = 0.0
            mains_supplied = 0.0
            if indirect:
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
                        pump_flow = min(max(water, 0.0), requested_input)
                        if filtration_pump_capacity > 0.0:
                            pump_flow = min(pump_flow, filtration_pump_capacity)
                        filter_throughput = pump_flow * filter_recovery
                        filter_loss = pump_flow - filter_throughput
                        water = max(water - pump_flow, 0.0)
                        if component_params.municipal_backup_enabled:
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
                    pump_flow = min(max(water, 0.0), requested_input)
                    if filtration_pump_capacity > 0.0:
                        pump_flow = min(pump_flow, filtration_pump_capacity)
                    filter_throughput = pump_flow * filter_recovery
                    filter_loss = pump_flow - filter_throughput
                    water = max(water - pump_flow, 0.0)
                    rainwater_supplied = min(filter_throughput, demand_hour)
            else:
                rainwater_supplied = min(max(water, 0.0), demand_hour)
                if pump_capacity > 0.0:
                    rainwater_supplied = min(rainwater_supplied, pump_capacity)
                pump_flow = rainwater_supplied
                water = max(water - rainwater_supplied, 0.0)
            met = rainwater_supplied >= demand_hour
            unmet = max(demand_hour - rainwater_supplied, 0.0)
            if not (indirect and booster_capacity > 0.0):
                mains_makeup = unmet if component_params.municipal_backup_enabled else 0.0
                mains_supplied = mains_makeup
                system_unmet = max(unmet - mains_makeup, 0.0)
            else:
                system_unmet = max(demand_hour - rainwater_supplied - mains_supplied, 0.0)
            collected_hour = float(collected.iloc[day_index]) if hour == 23 else 0.0
            water += collected_hour
            overflow = max(water - tank_size_gallons, 0.0)
            water = min(max(water, 0.0), tank_size_gallons)
            stored_after = water + booster_water
            mass_balance_error = (
                collected_hour + mains_makeup
                - rainwater_supplied - mains_supplied - filter_loss - overflow
                - (stored_after - stored_before)
            )
            met_hours += int(met)
            rows.append(
                {
                    "Date": pd.Timestamp(date) + pd.Timedelta(hours=hour),
                    "SystemType": system.system_type,
                    "CollectedGallons": collected_hour,
                    "DemandGallons": demand_hour,
                    "DemandMet": met,
                    "UnmetDemandGallons": unmet,
                    "SystemUnmetDemandGallons": system_unmet,
                    "MainsMakeupGallons": mains_makeup,
                    "MainsSuppliedGallons": mains_supplied,
                    "PumpFlowGallons": pump_flow,
                    "FilterThroughputGallons": filter_throughput,
                    "FilterLossGallons": filter_loss,
                    "BoosterTankGallons": booster_water,
                    "BoosterRefillActive": refill_active,
                    "OverflowGallons": overflow,
                    "WaterInTankGallons": water,
                    "MassBalanceErrorGallons": mass_balance_error,
                }
            )
    reliability = met_hours / len(rows) * 100.0 if rows else 0.0
    result = pd.DataFrame(rows)
    overall_balance_error = (
        float(result["MassBalanceErrorGallons"].sum()) if not result.empty else 0.0
    )
    return result.assign(
        ReliabilityPercent=reliability,
        OverallMassBalanceErrorGallons=overall_balance_error,
    )


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
    total = len(tank_sizes)
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
        rows.append({"TankSizeGallons": float(tank_size), "ReliabilityPercent": reliability})
        if progress_callback is not None:
            progress_callback(index, total, float(tank_size))

    return pd.DataFrame(rows)
