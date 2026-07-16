import pandas as pd

from rainwater_app.defaults import default_project_config
from rainwater_app.models import ProjectConfig, Surface
from rainwater_app.optimization import (
    BoosterTankProduct,
    FiltrationPumpProduct,
    PrimaryTankProduct,
    optimize_indirect_system,
)


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
    results = optimize_indirect_system(
        config,
        rainfall,
        primary_tanks=(
            PrimaryTankProduct("Small", 500.0, 500.0),
            PrimaryTankProduct("Large", 1_000.0, 1_500.0),
        ),
        filtration_pumps=(FiltrationPumpProduct("Pump", 300.0, 0.5, 250.0),),
        booster_tanks=(BoosterTankProduct("Booster", 100.0, 100.0),),
    )

    assert len(results) == 2
    assert [result.rank for result in results] == [1, 2]
    assert results[0].simple_payback_years <= results[1].simple_payback_years
    assert results[0].average_annual_energy_kwh >= 0.0


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
