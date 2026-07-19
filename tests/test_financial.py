import pandas as pd
import pytest

from rainwater_app.financial import (
    GALLONS_PER_CUBIC_METRE,
    average_annual_rainwater_supplied,
    calculate_financial_results,
    calculate_financial_results_from_annual_supply,
    tariff_rate_per_gallon,
)


def _two_year_results() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-01", "2024-01-02", "2025-01-01"]),
            "DemandGallons": [100.0, 100.0, 200.0],
            "UnmetDemandGallons": [25.0, 0.0, 50.0],
        }
    )


def test_average_annual_supply_uses_delivered_rainwater_by_modelled_year() -> None:
    assert average_annual_rainwater_supplied(_two_year_results()) == pytest.approx(162.5)


def test_financial_results_reconcile_savings_maintenance_and_payback() -> None:
    results = calculate_financial_results(
        _two_year_results(),
        water_rate=10.0,
        sewer_rate=20.0,
        billing_unit="per 1,000 gal",
        sewer_eligible_percent=50.0,
        installed_cost=100.0,
        incentives=20.0,
        fixed_annual_maintenance=1.0,
        maintenance_percent=1.0,
        analysis_period_years=20,
    )

    assert results.average_annual_supplied_gallons == pytest.approx(162.5)
    assert results.annual_municipal_water_savings == pytest.approx(1.625)
    assert results.annual_sewer_savings == pytest.approx(1.625)
    assert results.gross_annual_savings == pytest.approx(3.25)
    assert results.annual_maintenance_cost == pytest.approx(2.0)
    assert results.net_annual_savings == pytest.approx(1.25)
    assert results.net_installed_cost == pytest.approx(80.0)
    assert results.simple_payback_years == pytest.approx(64.0)
    assert results.analysis_period_net_benefit == pytest.approx(-55.0)


def test_financial_results_can_be_calculated_from_candidate_annual_supply() -> None:
    results = calculate_financial_results_from_annual_supply(
        162.5,
        water_rate=10.0,
        sewer_rate=20.0,
        billing_unit="per 1,000 gal",
        sewer_eligible_percent=50.0,
        installed_cost=100.0,
        incentives=20.0,
        fixed_annual_maintenance=1.0,
        maintenance_percent=1.0,
        analysis_period_years=20,
    )

    assert results.net_annual_savings == pytest.approx(1.25)
    assert results.simple_payback_years == pytest.approx(64.0)


def test_non_positive_net_savings_reports_payback_not_achieved() -> None:
    results = calculate_financial_results(
        _two_year_results(),
        water_rate=0.0,
        sewer_rate=0.0,
        billing_unit="per 1,000 gal",
        sewer_eligible_percent=100.0,
        installed_cost=1000.0,
        incentives=0.0,
        fixed_annual_maintenance=10.0,
        maintenance_percent=0.0,
        analysis_period_years=20,
    )

    assert results.simple_payback_years is None


def test_metric_tariff_unit_is_normalized_to_gallons() -> None:
    assert tariff_rate_per_gallon(1.0, "per m³") == pytest.approx(1.0 / GALLONS_PER_CUBIC_METRE)


@pytest.mark.parametrize(
    "overrides",
    [
        {"water_rate": -1.0},
        {"installed_cost": -1.0},
        {"sewer_eligible_percent": 101.0},
        {"maintenance_percent": -1.0},
        {"analysis_period_years": 0},
    ],
)
def test_invalid_financial_inputs_are_rejected(overrides: dict[str, float]) -> None:
    inputs = {
        "water_rate": 1.0,
        "sewer_rate": 1.0,
        "billing_unit": "per 1,000 gal",
        "sewer_eligible_percent": 100.0,
        "installed_cost": 1000.0,
        "incentives": 0.0,
        "fixed_annual_maintenance": 0.0,
        "maintenance_percent": 0.0,
        "analysis_period_years": 20,
    }
    inputs.update(overrides)

    with pytest.raises(ValueError):
        calculate_financial_results(_two_year_results(), **inputs)
