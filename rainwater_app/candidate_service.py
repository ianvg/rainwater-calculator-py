"""Candidate-result calculation, sorting, display, and export preparation."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .financial_service import FinancialAnalysisService
from .models import ProjectConfig
from .units import volume_to_display, volume_unit


HYDRAULIC_COLUMNS = (
    "TankSizeGallons",
    "ReliabilityPercent",
    "TotalDemandGallons",
    "RainwaterSuppliedGallons",
    "AverageAnnualRainwaterSuppliedGallons",
    "SewerEligibleRainwaterSuppliedGallons",
    "AverageAnnualSewerEligibleRainwaterSuppliedGallons",
    "AverageAnnualPumpFlowGallons",
    "UnmetDemandGallons",
    "MunicipalMakeupGallons",
    "SystemUnmetDemandGallons",
    "OverflowGallons",
    "FirstFlushLossGallons",
    "TreatmentLossGallons",
    "FinalStorageGallons",
)


@dataclass(frozen=True)
class CandidateAnalysisService:
    config: ProjectConfig

    def build(self, curve_df: pd.DataFrame) -> pd.DataFrame:
        data = curve_df.copy()
        for column in HYDRAULIC_COLUMNS:
            if column not in data:
                data[column] = pd.NA
        data["NetAnnualSavings"] = pd.NA
        data["SimplePaybackYears"] = pd.NA
        data["LifecycleNPV"] = pd.NA
        financial = FinancialAnalysisService(self.config)
        params = self.config.financial_parameters
        if not financial.is_configured():
            return data
        for index, supplied in data["AverageAnnualRainwaterSuppliedGallons"].items():
            if pd.isna(supplied):
                continue
            try:
                average_pump_flow = data.at[index, "AverageAnnualPumpFlowGallons"]
                if params.pump_power_kw > 0.0 and params.pump_flow_rate_gallons_per_hour <= 0.0:
                    raise ValueError(
                        "Enter a positive pump flow rate when pump power is greater than zero."
                    )
                average_pump_energy = (
                    0.0
                    if pd.isna(average_pump_flow) or params.pump_power_kw <= 0.0
                    else float(average_pump_flow)
                    / params.pump_flow_rate_gallons_per_hour
                    * params.pump_power_kw
                )
                eligible = data.at[
                    index, "AverageAnnualSewerEligibleRainwaterSuppliedGallons"
                ]
                result = financial.calculate_for_annual_supply(
                    float(supplied),
                    sewer_eligible_supplied_gallons=(
                        None if pd.isna(eligible) else float(eligible)
                    ),
                    average_annual_pump_energy_kwh=average_pump_energy,
                )
            except ValueError:
                continue
            data.at[index, "NetAnnualSavings"] = result.net_annual_savings
            data.at[index, "SimplePaybackYears"] = result.simple_payback_years
            data.at[index, "LifecycleNPV"] = result.lifecycle_net_present_value
        return data

    @staticmethod
    def sorted_data(
        data: pd.DataFrame, column: str | None, reverse: bool = False
    ) -> pd.DataFrame:
        if column not in data:
            return data.copy()
        return data.sort_values(
            column, ascending=not reverse, na_position="last", kind="stable"
        )

    def display_rows(
        self, data: pd.DataFrame, columns: tuple[str, ...]
    ) -> list[list[str]]:
        volume_columns = {
            "TankSizeGallons", "TotalDemandGallons", "RainwaterSuppliedGallons",
            "SewerEligibleRainwaterSuppliedGallons", "UnmetDemandGallons",
            "MunicipalMakeupGallons", "SystemUnmetDemandGallons", "OverflowGallons",
            "FirstFlushLossGallons", "TreatmentLossGallons", "FinalStorageGallons",
        }
        rows: list[list[str]] = []
        for record in data.to_dict("records"):
            display: list[str] = []
            for column in columns:
                value = record.get(column)
                if pd.isna(value):
                    display.append("--")
                elif column in volume_columns:
                    display.append(
                        f"{volume_to_display(float(value), self.config):,.0f}"
                    )
                elif column == "ReliabilityPercent":
                    display.append(f"{float(value):.1f}")
                elif column in {"NetAnnualSavings", "LifecycleNPV"}:
                    display.append(f"{float(value):,.2f}")
                elif column == "SimplePaybackYears":
                    display.append(f"{float(value):.1f}")
                else:
                    display.append(str(value))
            rows.append(display)
        return rows

    def export_data(self, data: pd.DataFrame) -> pd.DataFrame:
        export = data.copy()
        unit = volume_unit(self.config)
        volume_columns = [column for column in export if column.endswith("Gallons")]
        for column in volume_columns:
            export[column] = pd.to_numeric(export[column], errors="coerce").map(
                lambda value: volume_to_display(float(value), self.config)
                if pd.notna(value)
                else value
            )
        return export.rename(
            columns={
                column: column.replace("Gallons", f" ({unit})")
                for column in volume_columns
            }
        )
