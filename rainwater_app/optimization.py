from __future__ import annotations

import copy
from dataclasses import dataclass
import itertools
import math
from typing import Callable, Sequence

import pandas as pd

from .engine import simulate_hourly_tank
from .financial import average_annual_rainwater_supplied, tariff_rate_per_gallon
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


def _annual_average(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or "Date" not in frame or column not in frame:
        return 0.0
    values = frame[["Date", column]].copy()
    values["Date"] = pd.to_datetime(values["Date"], errors="coerce")
    values[column] = pd.to_numeric(values[column], errors="coerce").fillna(0.0)
    values = values.dropna(subset=["Date"])
    annual = values.groupby(values["Date"].dt.year)[column].sum()
    return float(annual.mean()) if not annual.empty else 0.0


def optimize_indirect_system(
    config: ProjectConfig,
    rainfall_df: pd.DataFrame,
    *,
    primary_tanks: Sequence[PrimaryTankProduct] = PRIMARY_TANK_CATALOG,
    filtration_pumps: Sequence[FiltrationPumpProduct] = FILTRATION_PUMP_CATALOG,
    booster_tanks: Sequence[BoosterTankProduct] = BOOSTER_TANK_CATALOG,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[OptimizationResult]:
    settings = config.optimization_parameters
    if not 0.0 <= settings.minimum_reliability_percent <= 100.0:
        raise ValueError("Minimum reliability must be between 0% and 100%.")
    if settings.electricity_rate_per_kwh < 0.0:
        raise ValueError("Electricity price cannot be negative.")
    if rainfall_df.empty:
        raise ValueError("Import daily rainfall data before running optimization.")
    products = list(itertools.product(primary_tanks, filtration_pumps, booster_tanks))
    if not products:
        raise ValueError("The optimization catalog must contain all three product types.")
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
    sewer_value = (
        tariff_rate_per_gallon(financial.sewer_rate, financial.tariff_billing_unit)
        * min(max(financial.sewer_eligible_percent, 0.0), 100.0)
        / 100.0
    )
    raw: list[OptimizationResult] = []
    for index, (tank, pump, booster) in enumerate(products, start=1):
        candidate = copy.deepcopy(config)
        candidate.system_type = "Indirect system"
        candidate.system_parameters.filtration_pump_capacity_gallons_per_hour = pump.capacity_gallons_per_hour
        candidate.system_parameters.booster_tank_size_gallons = booster.capacity_gallons
        results = simulate_hourly_tank(candidate, rainfall_df, tank.capacity_gallons)
        reliability = float(results["ReliabilityPercent"].iloc[0]) if not results.empty else 0.0
        supplied = average_annual_rainwater_supplied(results)
        runtime_hours = results["PumpFlowGallons"].clip(lower=0.0).sum() / pump.capacity_gallons_per_hour
        modeled_years = max(pd.to_datetime(results["Date"]).dt.year.nunique(), 1)
        annual_energy = float(runtime_hours * pump.power_kw / modeled_years)
        installed = financial.installed_cost + tank.installed_cost + pump.installed_cost + booster.installed_cost
        maintenance = financial.fixed_annual_maintenance + installed * financial.annual_maintenance_percent / 100.0
        net_savings = supplied * (water_value + sewer_value) - maintenance - annual_energy * settings.electricity_rate_per_kwh
        net_cost = max(installed - financial.incentives, 0.0)
        payback = net_cost / net_savings if net_savings > 0.0 else None
        if payback is not None and not math.isfinite(payback):
            payback = None
        raw.append(OptimizationResult(None, reliability >= settings.minimum_reliability_percent, tank, pump, booster, reliability, supplied, annual_energy, installed, net_savings, payback))
        if progress_callback:
            progress_callback(index, len(products))
    raw.sort(key=lambda item: (not item.feasible, item.simple_payback_years is None, item.simple_payback_years or math.inf, -item.net_annual_savings))
    rank = 0
    ranked: list[OptimizationResult] = []
    for item in raw:
        if item.feasible:
            rank += 1
        ranked.append(OptimizationResult(rank if item.feasible else None, item.feasible, item.primary_tank, item.filtration_pump, item.booster_tank, item.reliability_percent, item.average_annual_supplied_gallons, item.average_annual_energy_kwh, item.total_installed_cost, item.net_annual_savings, item.simple_payback_years))
    return ranked
