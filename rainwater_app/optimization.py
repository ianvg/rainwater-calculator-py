from __future__ import annotations

import copy
from collections import OrderedDict
from dataclasses import dataclass
import itertools
import math
from typing import Callable, Sequence

import pandas as pd

from .analysis_state import analysis_input_signature
from .engine import PreparedHourlyInputs, prepare_hourly_inputs, simulate_hourly_indirect_aggregates
from .financial import tariff_rate_per_gallon
from .models import ProjectConfig


@dataclass(frozen=True)
class PrimaryTankProduct:
    name: str
    capacity_gallons: float
    installed_cost: float


@dataclass(frozen=True)
class FiltrationPumpProduct:
    name: str
    capacity_gallons_per_hour: float
    power_kw: float
    installed_cost: float


@dataclass(frozen=True)
class BoosterTankProduct:
    name: str
    capacity_gallons: float
    installed_cost: float


@dataclass(frozen=True)
class OptimizationResult:
    rank: int | None
    feasible: bool
    primary_tank: PrimaryTankProduct
    filtration_pump: FiltrationPumpProduct
    booster_tank: BoosterTankProduct
    reliability_percent: float
    average_annual_supplied_gallons: float
    average_annual_energy_kwh: float
    total_installed_cost: float
    net_annual_savings: float
    simple_payback_years: float | None
    average_annual_municipal_makeup_gallons: float
    average_annual_overflow_gallons: float
    analysis_period_net_benefit: float


# Illustrative planning data only. These are not vendor products or market quotations.
PRIMARY_TANK_CATALOG = (
    PrimaryTankProduct("PT-1000", 1_000.0, 4_000.0),
    PrimaryTankProduct("PT-2500", 2_500.0, 6_500.0),
    PrimaryTankProduct("PT-5000", 5_000.0, 9_500.0),
)
FILTRATION_PUMP_CATALOG = (
    FiltrationPumpProduct("FP-5", 300.0, 0.37, 1_200.0),
    FiltrationPumpProduct("FP-10", 600.0, 0.55, 1_700.0),
    FiltrationPumpProduct("FP-20", 1_200.0, 1.10, 2_500.0),
)
BOOSTER_TANK_CATALOG = (
    BoosterTankProduct("BT-50", 50.0, 700.0),
    BoosterTankProduct("BT-100", 100.0, 1_000.0),
    BoosterTankProduct("BT-250", 250.0, 1_600.0),
)


_PREPARED_INPUT_CACHE: OrderedDict[str, PreparedHourlyInputs] = OrderedDict()
_MAX_PREPARED_CACHE_ENTRIES = 4


def _cached_prepared_inputs(config: ProjectConfig, rainfall_df: pd.DataFrame) -> PreparedHourlyInputs:
    key = analysis_input_signature(config, rainfall_df)
    cached = _PREPARED_INPUT_CACHE.get(key)
    if cached is not None:
        _PREPARED_INPUT_CACHE.move_to_end(key)
        return cached
    prepared = prepare_hourly_inputs(config, rainfall_df)
    _PREPARED_INPUT_CACHE[key] = prepared
    while len(_PREPARED_INPUT_CACHE) > _MAX_PREPARED_CACHE_ENTRIES:
        _PREPARED_INPUT_CACHE.popitem(last=False)
    return prepared


def optimize_indirect_system(
    config: ProjectConfig,
    rainfall_df: pd.DataFrame,
    *,
    primary_tanks: Sequence[PrimaryTankProduct] | None = None,
    filtration_pumps: Sequence[FiltrationPumpProduct] | None = None,
    booster_tanks: Sequence[BoosterTankProduct] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[OptimizationResult]:
    settings = config.optimization_parameters
    if primary_tanks is None or filtration_pumps is None or booster_tanks is None:
        catalog = settings.catalog
        if catalog:
            primary_tanks = tuple(
                PrimaryTankProduct(str(row["name"]), float(row["capacity"]), float(row["cost"]))
                for row in catalog if row.get("category") == "Primary tank"
            )
            filtration_pumps = tuple(
                FiltrationPumpProduct(
                    str(row["name"]), float(row["capacity"]), float(row.get("power_kw", 0.0)), float(row["cost"])
                ) for row in catalog if row.get("category") == "Filtration pump"
            )
            booster_tanks = tuple(
                BoosterTankProduct(str(row["name"]), float(row["capacity"]), float(row["cost"]))
                for row in catalog
                if row.get("category") in {"Buffer tank", "Booster tank"}
            )
        else:
            primary_tanks = PRIMARY_TANK_CATALOG
            filtration_pumps = FILTRATION_PUMP_CATALOG
            booster_tanks = BOOSTER_TANK_CATALOG
    if not 0.0 <= settings.minimum_reliability_percent <= 100.0:
        raise ValueError("Minimum reliability must be between 0% and 100%.")
    if settings.electricity_rate_per_kwh < 0.0:
        raise ValueError("Electricity price cannot be negative.")
    if settings.maximum_annual_municipal_makeup_gallons is not None and settings.maximum_annual_municipal_makeup_gallons < 0.0:
        raise ValueError("Maximum annual municipal makeup cannot be negative.")
    if settings.maximum_installed_cost is not None and settings.maximum_installed_cost < 0.0:
        raise ValueError("Maximum installed cost cannot be negative.")
    supported_objectives = {
        "Simple payback", "Net annual savings", "Rainwater reliability", "Analysis-period net benefit"
    }
    if settings.objective not in supported_objectives:
        raise ValueError("Select a supported optimization objective.")
    if rainfall_df.empty:
        raise ValueError("Import daily rainfall data before running optimization.")
    products = list(itertools.product(primary_tanks, filtration_pumps, booster_tanks))
    if not products:
        raise ValueError("The optimization catalog must contain all three product types.")
    if any(item.capacity_gallons <= 0.0 or item.installed_cost < 0.0 for item in primary_tanks):
        raise ValueError("Primary tank catalog values must have positive capacity and non-negative cost.")
    if any(item.capacity_gallons_per_hour <= 0.0 or item.power_kw < 0.0 or item.installed_cost < 0.0 for item in filtration_pumps):
        raise ValueError("Filtration pump catalog values must have positive capacity and non-negative power and cost.")
    if any(item.capacity_gallons <= 0.0 or item.installed_cost < 0.0 for item in booster_tanks):
        raise ValueError("Buffer tank catalog values must have positive capacity and non-negative cost.")
    financial = config.financial_parameters
    if any(value < 0.0 for value in (
        financial.installed_cost, financial.incentives, financial.fixed_annual_maintenance
    )):
        raise ValueError("Costs and incentives cannot be negative.")
    if not 0.0 <= financial.annual_maintenance_percent <= 100.0:
        raise ValueError("Maintenance percentage must be between 0% and 100%.")
    if not 0.0 <= financial.sewer_eligible_percent <= 100.0:
        raise ValueError("Sewer-eligible supply must be between 0% and 100%.")
    water_value = tariff_rate_per_gallon(financial.water_rate, financial.tariff_billing_unit)
    sewer_value = tariff_rate_per_gallon(
        financial.sewer_rate, financial.tariff_billing_unit
    )
    raw: list[OptimizationResult] = []
    prepared = _cached_prepared_inputs(config, rainfall_df)
    for index, (tank, pump, booster) in enumerate(products, start=1):
        candidate = copy.deepcopy(config)
        candidate.system_type = "Indirect system"
        candidate.system_parameters.filtration_pump_capacity_gallons_per_hour = pump.capacity_gallons_per_hour
        candidate.system_parameters.booster_tank_size_gallons = booster.capacity_gallons
        aggregates = simulate_hourly_indirect_aggregates(candidate, prepared, tank.capacity_gallons)
        reliability = aggregates.reliability_percent
        supplied = aggregates.average_annual_supplied_gallons
        sewer_eligible_supplied = aggregates.average_annual_sewer_eligible_supplied_gallons
        municipal_makeup = aggregates.average_annual_municipal_makeup_gallons
        overflow = aggregates.average_annual_overflow_gallons
        annual_energy = aggregates.average_annual_pump_flow_gallons / pump.capacity_gallons_per_hour * pump.power_kw
        installed = financial.installed_cost + tank.installed_cost + pump.installed_cost + booster.installed_cost
        maintenance = financial.fixed_annual_maintenance + installed * financial.annual_maintenance_percent / 100.0
        net_savings = (
            supplied * water_value
            + sewer_eligible_supplied * sewer_value
            - maintenance
            - annual_energy * settings.electricity_rate_per_kwh
        )
        net_cost = max(installed - financial.incentives, 0.0)
        payback = net_cost / net_savings if net_savings > 0.0 else None
        if payback is not None and not math.isfinite(payback):
            payback = None
        period_benefit = net_savings * financial.analysis_period_years - net_cost
        feasible = reliability >= settings.minimum_reliability_percent
        if settings.maximum_annual_municipal_makeup_gallons is not None:
            feasible = feasible and municipal_makeup <= settings.maximum_annual_municipal_makeup_gallons
        if settings.maximum_installed_cost is not None:
            feasible = feasible and installed <= settings.maximum_installed_cost
        if settings.require_positive_net_savings:
            feasible = feasible and net_savings > 0.0
        raw.append(OptimizationResult(None, feasible, tank, pump, booster, reliability, supplied, annual_energy, installed, net_savings, payback, municipal_makeup, overflow, period_benefit))
        if progress_callback:
            progress_callback(index, len(products))
    objective = settings.objective
    if objective == "Net annual savings":
        objective_key = lambda item: (-item.net_annual_savings,)
    elif objective == "Rainwater reliability":
        objective_key = lambda item: (-item.reliability_percent, item.total_installed_cost)
    elif objective == "Analysis-period net benefit":
        objective_key = lambda item: (-item.analysis_period_net_benefit,)
    else:
        objective_key = lambda item: (item.simple_payback_years is None, item.simple_payback_years or math.inf)
    raw.sort(key=lambda item: (not item.feasible, *objective_key(item), -item.net_annual_savings))
    rank = 0
    ranked: list[OptimizationResult] = []
    for item in raw:
        if item.feasible:
            rank += 1
        ranked.append(OptimizationResult(rank if item.feasible else None, item.feasible, item.primary_tank, item.filtration_pump, item.booster_tank, item.reliability_percent, item.average_annual_supplied_gallons, item.average_annual_energy_kwh, item.total_installed_cost, item.net_annual_savings, item.simple_payback_years, item.average_annual_municipal_makeup_gallons, item.average_annual_overflow_gallons, item.analysis_period_net_benefit))
    return ranked
