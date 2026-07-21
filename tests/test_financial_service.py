from __future__ import annotations

import pandas as pd
import pytest

from rainwater_app.defaults import default_project_config
from rainwater_app.financial_service import FinancialAnalysisService


def test_service_applies_persisted_lifecycle_assumptions() -> None:
    config = default_project_config("Lifecycle service")
    financial = config.financial_parameters
    financial.water_rate = 10.0
    financial.installed_cost = 1_000.0
    financial.discount_rate_percent = 5.0
    financial.pump_power_kw = 1.0
    financial.pump_flow_rate_gallons_per_hour = 100.0
    config.optimization_parameters.electricity_rate_per_kwh = 0.2
    source = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-01-01"]),
            "DemandGallons": [100_000.0],
            "UnmetDemandGallons": [0.0],
            "PumpFlowGallons": [1_000.0],
        }
    )

    result = FinancialAnalysisService(config).calculate(source)

    assert result.gross_annual_savings == pytest.approx(1_000.0)
    assert result.average_annual_pump_energy_kwh == pytest.approx(10.0)
    assert result.annual_pump_energy_cost == pytest.approx(2.0)
    assert result.lifecycle_net_present_value != result.analysis_period_net_benefit


def test_service_reports_whether_economic_inputs_are_configured() -> None:
    config = default_project_config("Configuration")
    service = FinancialAnalysisService(config)
    assert service.is_configured() is False

    config.financial_parameters.equipment_replacement_cost = 500.0
    assert service.is_configured() is True
