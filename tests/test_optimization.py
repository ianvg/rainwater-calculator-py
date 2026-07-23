import math

import pandas as pd
import pytest

from rainwater_app.defaults import default_project_config
from rainwater_app.models import ProjectConfig, Surface
from rainwater_app.optimization import (
    BoosterTankProduct,
    FiltrationPumpProduct,
    PrimaryTankProduct,
    optimize_indirect_system,
    _PREPARED_INPUT_CACHE,
    _cached_prepared_inputs,
)
from rainwater_app.engine import prepare_hourly_inputs, simulate_hourly_indirect_aggregates, simulate_hourly_tank
from rainwater_app.financial import average_annual_rainwater_supplied


def test_optimizer_filters_by_reliability_and_ranks_feasible_payback() -> None:
    config = default_project_config("Optimization")
    config.surfaces = [Surface("Roof", area=2_000.0, runoff_coefficient=0.9)]
    config.demand.simple_daily_demand_gallons = 100.0
    config.financial_parameters.water_rate = 50.0
    config.financial_parameters.sewer_rate = 50.0
    config.financial_parameters.installed_cost = 1_000.0
    config.optimization_parameters.minimum_reliability_percent = 0.0
    config.optimization_parameters.electricity_rate_per_kwh = 0.20
    rainfall = pd.DataFrame({
        "Date": pd.date_range("2025-01-01", periods=3, freq="D"),
        "Precipitation": [1.0, 0.0, 0.0],
    })
    progress_updates: list[tuple[int, int]] = []
    results = optimize_indirect_system(
        config,
        rainfall,
        primary_tanks=(
            PrimaryTankProduct("Small", 500.0, 500.0),
            PrimaryTankProduct("Large", 1_000.0, 1_500.0),
        ),
        filtration_pumps=(FiltrationPumpProduct("Pump", 900.0, 0.5, 250.0),),
        booster_tanks=(BoosterTankProduct("Booster", 100.0, 100.0),),
        progress_callback=lambda current, total: progress_updates.append((current, total)),
    )

    assert len(results) == 2
    assert [result.rank for result in results] == [1, 2]
    assert results[0].simple_payback_years <= results[1].simple_payback_years
    assert results[0].average_annual_energy_kwh >= 0.0
    assert all(math.isfinite(result.lifecycle_net_present_value) for result in results)
    assert progress_updates == [(1, 2), (2, 2)]


def test_optimizer_can_rank_by_lifecycle_npv() -> None:
    config = default_project_config("NPV optimization")
    config.surfaces = [Surface("Roof", area=2_000.0, runoff_coefficient=0.9)]
    config.demand.simple_daily_demand_gallons = 100.0
    config.financial_parameters.water_rate = 50.0
    config.financial_parameters.discount_rate_percent = 4.0
    config.optimization_parameters.minimum_reliability_percent = 0.0
    config.optimization_parameters.objective = "Lifecycle NPV"
    rainfall = pd.DataFrame({
        "Date": pd.date_range("2025-01-01", periods=3, freq="D"),
        "Precipitation": [1.0, 0.0, 0.0],
    })

    results = optimize_indirect_system(
        config,
        rainfall,
        primary_tanks=(
            PrimaryTankProduct("Small", 500.0, 500.0),
            PrimaryTankProduct("Large", 1_000.0, 1_500.0),
        ),
        filtration_pumps=(FiltrationPumpProduct("Pump", 900.0, 0.5, 250.0),),
        booster_tanks=(BoosterTankProduct("Booster", 100.0, 100.0),),
    )

    assert results[0].lifecycle_net_present_value >= results[1].lifecycle_net_present_value


def test_optimizer_rejects_invalid_minimum_reliability() -> None:
    config = ProjectConfig(name="Invalid")
    config.optimization_parameters.minimum_reliability_percent = 101.0
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    try:
        optimize_indirect_system(config, rainfall)
    except ValueError as exc:
        assert "between 0% and 100%" in str(exc)
    else:
        raise AssertionError("Expected invalid reliability to be rejected")


def test_optimizer_applies_installed_cost_constraint() -> None:
    config = default_project_config("Cost constraint")
    config.optimization_parameters.minimum_reliability_percent = 0.0
    config.optimization_parameters.maximum_installed_cost = 1_100.0
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})
    results = optimize_indirect_system(
        config, rainfall,
        primary_tanks=(PrimaryTankProduct("Tank", 500.0, 500.0),),
        filtration_pumps=(FiltrationPumpProduct("Pump", 900.0, 0.5, 250.0),),
        booster_tanks=(
            BoosterTankProduct("Within budget", 100.0, 100.0),
            BoosterTankProduct("Over budget", 200.0, 500.0),
        ),
    )

    assert results[0].booster_tank.name == "Within budget"
    assert results[0].feasible is True
    assert results[1].feasible is False


@pytest.mark.parametrize("booster_size", [0.0, 100.0])
def test_aggregate_hourly_path_matches_detailed_simulation(booster_size: float) -> None:
    config = default_project_config("Aggregate parity")
    config.system_type = "Indirect system"
    config.surfaces = [Surface("Roof", area=1_500.0, runoff_coefficient=0.85)]
    config.demand.simple_daily_demand_gallons = 120.0
    config.system_parameters.filtration_pump_capacity_gallons_per_hour = 60.0
    config.system_parameters.filter_recovery_percent = 90.0
    config.system_parameters.booster_tank_size_gallons = booster_size
    rainfall = pd.DataFrame({
        "Date": pd.date_range("2024-12-30", periods=5, freq="D"),
        "Precipitation": [0.0, 0.5, 0.0, 0.0, 0.2],
    })
    detailed = simulate_hourly_tank(config, rainfall, 800.0)
    aggregate = simulate_hourly_indirect_aggregates(
        config, prepare_hourly_inputs(config, rainfall), 800.0
    )
    annual_makeup = detailed.groupby(detailed["Date"].dt.year)["MainsMakeupGallons"].sum().mean()
    annual_overflow = detailed.groupby(detailed["Date"].dt.year)["OverflowGallons"].sum().mean()
    annual_pump = detailed.groupby(detailed["Date"].dt.year)["PumpFlowGallons"].sum().mean()

    assert aggregate.reliability_percent == pytest.approx(detailed["ReliabilityPercent"].iloc[0])
    assert aggregate.average_annual_supplied_gallons == pytest.approx(average_annual_rainwater_supplied(detailed))
    assert aggregate.average_annual_municipal_makeup_gallons == pytest.approx(annual_makeup)
    assert aggregate.average_annual_overflow_gallons == pytest.approx(annual_overflow)
    assert aggregate.average_annual_pump_flow_gallons == pytest.approx(annual_pump)


def test_prepared_hourly_inputs_are_cached_for_unchanged_inputs() -> None:
    config = default_project_config("Cached")
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})
    _PREPARED_INPUT_CACHE.clear()

    first = _cached_prepared_inputs(config, rainfall)
    second = _cached_prepared_inputs(config, rainfall.copy())

    assert first is second
