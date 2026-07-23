from __future__ import annotations

import copy
from collections import OrderedDict
from dataclasses import asdict, dataclass, replace
import hashlib
import itertools
import json
import math
import threading
from typing import Callable, Sequence

import pandas as pd

from .analysis_state import analysis_input_signature
from .engine import (
    AnalysisCancelledError,
    PreparedHourlyInputs,
    prepare_hourly_inputs,
    simulate_hourly_indirect_aggregates,
)
from .financial import calculate_financial_results_from_annual_supply
from .models import FILTRATION_SYSTEM_FLOW_RATES_GPM, ProjectConfig
from .equipment_catalog import (
    built_in_equipment_library,
    default_project_candidates,
    effective_candidate_product,
    evaluate_combination_compatibility,
    evaluate_product_eligibility,
    migrate_legacy_catalog,
)


@dataclass(frozen=True)
class PrimaryTankProduct:
    name: str
    capacity_gallons: float
    installed_cost: float
    product_id: str = ""


@dataclass(frozen=True)
class FiltrationPumpProduct:
    name: str
    capacity_gallons_per_hour: float
    power_kw: float
    installed_cost: float
    product_id: str = ""


@dataclass(frozen=True)
class FiltrationUnitProduct:
    name: str
    capacity_gallons_per_hour: float
    installed_cost: float
    minimum_flow_gpm: float | None = None
    maximum_flow_gpm: float | None = None
    recovery_percent: float | None = None
    product_id: str = ""


@dataclass(frozen=True)
class BoosterTankProduct:
    name: str
    capacity_gallons: float
    installed_cost: float
    product_id: str = ""


@dataclass(frozen=True)
class OptimizationResult:
    rank: int | None
    feasible: bool
    primary_tank: PrimaryTankProduct
    filtration_pump: FiltrationPumpProduct
    filtration_unit: FiltrationUnitProduct
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
    lifecycle_net_present_value: float
    internal_rate_of_return_percent: float | None
    discounted_payback_years: float | None


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
FILTRATION_UNIT_CATALOG = (
    FiltrationUnitProduct("FU-5-15", 900.0, 1_100.0, 5.0, 15.0),
    FiltrationUnitProduct("FU-10-25", 1_500.0, 1_650.0, 10.0, 25.0),
)


_PREPARED_INPUT_CACHE: OrderedDict[str, PreparedHourlyInputs] = OrderedDict()
_MAX_PREPARED_CACHE_ENTRIES = 4
_CANDIDATE_RESULT_CACHE: OrderedDict[str, OptimizationResult] = OrderedDict()
_MAX_CANDIDATE_RESULT_CACHE_ENTRIES = 2048
_CANDIDATE_RESULT_CACHE_LOCK = threading.Lock()


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


def _candidate_result_cache_key(
    simulation_signature: str,
    config: ProjectConfig,
    tank: PrimaryTankProduct,
    pump: FiltrationPumpProduct,
    filtration: FiltrationUnitProduct,
    booster: BoosterTankProduct,
) -> str:
    """Return a stable key for every input that changes a candidate evaluation."""
    payload = {
        "simulation_signature": simulation_signature,
        "financial_parameters": asdict(config.financial_parameters),
        "electricity_rate_per_kwh": float(
            config.optimization_parameters.electricity_rate_per_kwh
        ),
        "products": [
            asdict(tank),
            asdict(pump),
            asdict(filtration),
            asdict(booster),
        ],
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cached_candidate_result(key: str) -> OptimizationResult | None:
    with _CANDIDATE_RESULT_CACHE_LOCK:
        cached = _CANDIDATE_RESULT_CACHE.get(key)
        if cached is not None:
            _CANDIDATE_RESULT_CACHE.move_to_end(key)
        return cached


def _store_candidate_result(key: str, result: OptimizationResult) -> None:
    with _CANDIDATE_RESULT_CACHE_LOCK:
        _CANDIDATE_RESULT_CACHE[key] = result
        _CANDIDATE_RESULT_CACHE.move_to_end(key)
        while len(_CANDIDATE_RESULT_CACHE) > _MAX_CANDIDATE_RESULT_CACHE_ENTRIES:
            _CANDIDATE_RESULT_CACHE.popitem(last=False)


def optimize_indirect_system(
    config: ProjectConfig,
    rainfall_df: pd.DataFrame,
    *,
    primary_tanks: Sequence[PrimaryTankProduct] | None = None,
    filtration_pumps: Sequence[FiltrationPumpProduct] | None = None,
    filtration_units: Sequence[FiltrationUnitProduct] | None = None,
    booster_tanks: Sequence[BoosterTankProduct] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_callback: Callable[[], bool] | None = None,
    cache_callback: Callable[[bool], None] | None = None,
) -> list[OptimizationResult]:
    settings = config.optimization_parameters
    explicit_legacy_products = (
        primary_tanks is not None and filtration_pumps is not None and booster_tanks is not None
    )
    candidate_products: dict[str, list[dict[str, object]]] = {}
    if not explicit_legacy_products:
        candidates = list(settings.equipment_candidates)
        if not candidates and settings.catalog:
            candidates = migrate_legacy_catalog(settings.catalog)
        if not candidates:
            candidates = default_project_candidates(built_in_equipment_library())
        for candidate in candidates:
            if candidate.get("disposition", "Candidate") == "Excluded":
                continue
            product = effective_candidate_product(candidate)
            eligible, _reasons = evaluate_product_eligibility(product, settings.equipment_constraints)
            if eligible and product.get("active", True):
                candidate_products.setdefault(str(product["category"]), []).append(product)
        for category, products_in_category in list(candidate_products.items()):
            fixed_ids = {
                str(item.get("product_id")) for item in candidates
                if item.get("disposition") == "Fixed"
            }
            fixed = [item for item in products_in_category if str(item["id"]) in fixed_ids]
            if fixed:
                candidate_products[category] = fixed

        def prop(item: dict[str, object], key: str, default: object = 0.0) -> object:
            return dict(item.get("properties") or {}).get(key, default)

        primary_tanks = tuple(
            PrimaryTankProduct(str(item["model"]), float(item["capacity"]), float(item["installed_cost"]), str(item["id"]))
            for item in candidate_products.get("Primary tank", [])
        )
        filtration_pumps = tuple(
            FiltrationPumpProduct(str(item["model"]), float(item["capacity"]),
                                  float(prop(item, "power_kw")), float(item["installed_cost"]), str(item["id"]))
            for item in candidate_products.get("Transfer pump", [])
        )
        filtration_units = tuple(
            FiltrationUnitProduct(
                str(item["model"]), float(item["capacity"]), float(item["installed_cost"]),
                _optional_float(prop(item, "minimum_flow_gpm", None)),
                _optional_float(prop(item, "maximum_flow_gpm", None)),
                _optional_float(prop(item, "recovery_percent", None)),
                str(item["id"]),
            ) for item in candidate_products.get("Filtration system", [])
        )
        booster_tanks = tuple(
            BoosterTankProduct(str(item["model"]), float(item["capacity"]), float(item["installed_cost"]), str(item["id"]))
            for item in candidate_products.get("Buffer tank", [])
        )
    elif filtration_units is None:
        # Preserve the public three-sequence API with a linked filtration system.
        filtration_units = tuple(
            FiltrationUnitProduct(
                "Existing filtration", pump.capacity_gallons_per_hour, 0.0,
                pump.capacity_gallons_per_hour / 60.0,
                pump.capacity_gallons_per_hour / 60.0,
            )
            for pump in filtration_pumps
        )
    if not 0.0 <= settings.minimum_reliability_percent <= 100.0:
        raise ValueError("Minimum reliability must be between 0% and 100%.")
    if settings.electricity_rate_per_kwh < 0.0:
        raise ValueError("Electricity price cannot be negative.")
    if settings.maximum_annual_municipal_makeup_gallons is not None and settings.maximum_annual_municipal_makeup_gallons < 0.0:
        raise ValueError("Maximum annual municipal makeup cannot be negative.")
    if settings.maximum_installed_cost is not None and settings.maximum_installed_cost < 0.0:
        raise ValueError("Maximum installed cost cannot be negative.")
    supported_objectives = {
        "Simple payback", "Net annual savings", "Rainwater reliability",
        "Analysis-period net benefit", "Lifecycle NPV"
    }
    if settings.objective not in supported_objectives:
        raise ValueError("Select a supported optimization objective.")
    if rainfall_df.empty:
        raise ValueError("Import daily rainfall data before running optimization.")
    products = list(itertools.product(primary_tanks, filtration_pumps, filtration_units, booster_tanks))
    if candidate_products:
        source_by_key = {
            str(item["id"]): item
            for values in candidate_products.values() for item in values
        }
        products = [
            combination for combination in products
            if evaluate_combination_compatibility((
                source_by_key[combination[0].product_id],
                source_by_key[combination[1].product_id],
                source_by_key[combination[2].product_id],
                source_by_key[combination[3].product_id],
            ), settings.equipment_constraints)[0]
        ]
    if not products:
        raise ValueError("The project needs an eligible product in all four categories and at least one compatible combination.")
    if any(item.capacity_gallons <= 0.0 or item.installed_cost < 0.0 for item in primary_tanks):
        raise ValueError("Primary tank catalog values must have positive capacity and non-negative cost.")
    if any(item.capacity_gallons_per_hour <= 0.0 or item.power_kw < 0.0 or item.installed_cost < 0.0 for item in filtration_pumps):
        raise ValueError("Transfer pump catalog values must have positive capacity and non-negative power and cost.")
    if any(item.capacity_gallons_per_hour <= 0.0 or item.installed_cost < 0.0 for item in filtration_units):
            raise ValueError("Filtration-system catalog values must have positive capacity and non-negative cost.")
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
    raw: list[OptimizationResult] = []
    if cancel_callback is not None and cancel_callback():
        raise AnalysisCancelledError("Optimization cancelled by user.")
    prepared = _cached_prepared_inputs(config, rainfall_df)
    simulation_signature = analysis_input_signature(config, rainfall_df)
    for index, (tank, pump, filtration, booster) in enumerate(products, start=1):
        if cancel_callback is not None and cancel_callback():
            raise AnalysisCancelledError("Optimization cancelled by user.")
        flow_gpm = filtration.capacity_gallons_per_hour / 60.0
        if flow_gpm not in FILTRATION_SYSTEM_FLOW_RATES_GPM:
            raise ValueError("Filtration system flow must be 15, 20, 30, 40, or 50 GPM.")
        if pump.capacity_gallons_per_hour != filtration.capacity_gallons_per_hour:
            raise ValueError("Transfer pump flow must match the filtration system flow.")
        cache_key = _candidate_result_cache_key(
            simulation_signature, config, tank, pump, filtration, booster
        )
        base_result = _cached_candidate_result(cache_key)
        cache_hit = base_result is not None
        if cache_callback is not None:
            cache_callback(cache_hit)
        if base_result is None:
            candidate = copy.deepcopy(config)
            candidate.system_type = "Indirect system"
            candidate.system_parameters.filtration_system_flow_gpm = int(flow_gpm)
            candidate.system_parameters.synchronize_filtration_flow()
            if filtration.recovery_percent is not None:
                candidate.system_parameters.filter_recovery_percent = filtration.recovery_percent
            candidate.system_parameters.booster_tank_size_gallons = booster.capacity_gallons
            aggregates = simulate_hourly_indirect_aggregates(
                candidate,
                prepared,
                tank.capacity_gallons,
                cancel_callback=cancel_callback,
            )
            if cancel_callback is not None and cancel_callback():
                raise AnalysisCancelledError("Optimization cancelled by user.")
            supplied = aggregates.average_annual_supplied_gallons
            annual_energy = (
                aggregates.average_annual_pump_flow_gallons
                / pump.capacity_gallons_per_hour
                * pump.power_kw
            )
            installed = (
                financial.installed_cost
                + tank.installed_cost
                + pump.installed_cost
                + filtration.installed_cost
                + booster.installed_cost
            )
            lifecycle = calculate_financial_results_from_annual_supply(
                supplied,
                average_annual_sewer_eligible_supplied_gallons=(
                    aggregates.average_annual_sewer_eligible_supplied_gallons
                ),
                water_rate=financial.water_rate,
                sewer_rate=financial.sewer_rate,
                billing_unit=financial.tariff_billing_unit,
                sewer_eligible_percent=financial.sewer_eligible_percent,
                installed_cost=installed,
                incentives=financial.incentives,
                fixed_annual_maintenance=financial.fixed_annual_maintenance,
                maintenance_percent=financial.annual_maintenance_percent,
                analysis_period_years=financial.analysis_period_years,
                discount_rate_percent=financial.discount_rate_percent,
                utility_rate_escalation_percent=financial.utility_rate_escalation_percent,
                maintenance_escalation_percent=financial.maintenance_escalation_percent,
                average_annual_pump_energy_kwh=annual_energy,
                electricity_rate_per_kwh=settings.electricity_rate_per_kwh,
                electricity_escalation_percent=financial.electricity_escalation_percent,
                equipment_replacement_cost=financial.equipment_replacement_cost,
                equipment_replacement_interval_years=(
                    financial.equipment_replacement_interval_years
                ),
                equipment_replacement_escalation_percent=(
                    financial.equipment_replacement_escalation_percent
                ),
            )
            base_result = OptimizationResult(
                None,
                False,
                tank,
                pump,
                filtration,
                booster,
                aggregates.reliability_percent,
                supplied,
                annual_energy,
                installed,
                lifecycle.net_annual_savings,
                lifecycle.simple_payback_years,
                aggregates.average_annual_municipal_makeup_gallons,
                aggregates.average_annual_overflow_gallons,
                lifecycle.analysis_period_net_benefit,
                lifecycle.lifecycle_net_present_value,
                lifecycle.internal_rate_of_return_percent,
                lifecycle.discounted_payback_years,
            )
            _store_candidate_result(cache_key, base_result)
        feasible = base_result.reliability_percent >= settings.minimum_reliability_percent
        if settings.maximum_annual_municipal_makeup_gallons is not None:
            feasible = feasible and base_result.average_annual_municipal_makeup_gallons <= settings.maximum_annual_municipal_makeup_gallons
        if settings.maximum_installed_cost is not None:
            feasible = feasible and base_result.total_installed_cost <= settings.maximum_installed_cost
        if settings.require_positive_net_savings:
            feasible = feasible and base_result.net_annual_savings > 0.0
        raw.append(replace(base_result, feasible=feasible))
        if progress_callback:
            progress_callback(index, len(products))
    objective = settings.objective
    if objective == "Net annual savings":
        objective_key = lambda item: (-item.net_annual_savings,)
    elif objective == "Rainwater reliability":
        objective_key = lambda item: (-item.reliability_percent, item.total_installed_cost)
    elif objective == "Analysis-period net benefit":
        objective_key = lambda item: (-item.analysis_period_net_benefit,)
    elif objective == "Lifecycle NPV":
        objective_key = lambda item: (-item.lifecycle_net_present_value,)
    else:
        objective_key = lambda item: (item.simple_payback_years is None, item.simple_payback_years or math.inf)
    raw.sort(key=lambda item: (not item.feasible, *objective_key(item), -item.net_annual_savings))
    rank = 0
    ranked: list[OptimizationResult] = []
    for item in raw:
        if item.feasible:
            rank += 1
        ranked.append(
            OptimizationResult(
                rank if item.feasible else None, item.feasible, item.primary_tank,
                item.filtration_pump, item.filtration_unit, item.booster_tank, item.reliability_percent,
                item.average_annual_supplied_gallons, item.average_annual_energy_kwh,
                item.total_installed_cost, item.net_annual_savings,
                item.simple_payback_years,
                item.average_annual_municipal_makeup_gallons,
                item.average_annual_overflow_gallons,
                item.analysis_period_net_benefit,
                item.lifecycle_net_present_value,
                item.internal_rate_of_return_percent,
                item.discounted_payback_years,
            )
        )
    return ranked


def _optional_float(value: object) -> float | None:
    return None if value in (None, "") else float(value)
