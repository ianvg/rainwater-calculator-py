"""UI-independent orchestration for lifecycle financial analysis."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .financial import (
    FinancialResults,
    calculate_financial_results,
    calculate_financial_results_from_annual_supply,
)
from .models import ProjectConfig


@dataclass(frozen=True)
class FinancialAnalysisService:
    """Apply one project's persisted assumptions consistently to financial calculations."""

    config: ProjectConfig

    def calculation_kwargs(self) -> dict[str, object]:
        params = self.config.financial_parameters
        return {
            "water_rate": params.water_rate,
            "sewer_rate": params.sewer_rate,
            "billing_unit": params.tariff_billing_unit,
            "sewer_eligible_percent": params.sewer_eligible_percent,
            "installed_cost": params.installed_cost,
            "incentives": params.incentives,
            "fixed_annual_maintenance": params.fixed_annual_maintenance,
            "maintenance_percent": params.annual_maintenance_percent,
            "analysis_period_years": params.analysis_period_years,
            "discount_rate_percent": params.discount_rate_percent,
            "utility_rate_escalation_percent": params.utility_rate_escalation_percent,
            "maintenance_escalation_percent": params.maintenance_escalation_percent,
            "electricity_rate_per_kwh": (
                self.config.optimization_parameters.electricity_rate_per_kwh
            ),
            "electricity_escalation_percent": params.electricity_escalation_percent,
            "pump_power_kw": params.pump_power_kw,
            "pump_flow_rate_gallons_per_hour": (
                params.pump_flow_rate_gallons_per_hour
            ),
            "equipment_replacement_cost": params.equipment_replacement_cost,
            "equipment_replacement_interval_years": (
                params.equipment_replacement_interval_years
            ),
            "equipment_replacement_escalation_percent": (
                params.equipment_replacement_escalation_percent
            ),
        }

    def calculate(self, results_df: pd.DataFrame) -> FinancialResults:
        return calculate_financial_results(results_df, **self.calculation_kwargs())

    def calculate_for_annual_supply(
        self,
        supplied_gallons: float,
        *,
        sewer_eligible_supplied_gallons: float | None = None,
        average_annual_pump_energy_kwh: float = 0.0,
        installed_cost: float | None = None,
    ) -> FinancialResults:
        values = self.calculation_kwargs()
        values.pop("pump_power_kw")
        values.pop("pump_flow_rate_gallons_per_hour")
        values["average_annual_pump_energy_kwh"] = average_annual_pump_energy_kwh
        if installed_cost is not None:
            values["installed_cost"] = installed_cost
        return calculate_financial_results_from_annual_supply(
            supplied_gallons,
            average_annual_sewer_eligible_supplied_gallons=(
                sewer_eligible_supplied_gallons
            ),
            **values,
        )

    def is_configured(self) -> bool:
        params = self.config.financial_parameters
        return any(
            float(value) > 0.0
            for value in (
                params.water_rate,
                params.sewer_rate,
                params.installed_cost,
                params.incentives,
                params.fixed_annual_maintenance,
                params.annual_maintenance_percent,
                params.pump_power_kw,
                params.equipment_replacement_cost,
            )
        )
