from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd

GALLONS_PER_CUBIC_METRE = 264.172052
SUPPORTED_TARIFF_UNITS = {"per 1,000 gal", "per m³"}


@dataclass(frozen=True)
class FinancialResults:
    average_annual_supplied_gallons: float
    average_annual_sewer_eligible_supplied_gallons: float
    annual_municipal_water_savings: float
    annual_sewer_savings: float
    gross_annual_savings: float
    annual_maintenance_cost: float
    net_annual_savings: float
    net_installed_cost: float
    simple_payback_years: float | None
    analysis_period_net_benefit: float


def tariff_rate_per_gallon(rate: float, billing_unit: str) -> float:
    if rate < 0:
        raise ValueError("Utility rates cannot be negative.")
    if billing_unit == "per 1,000 gal":
        return rate / 1000.0
    if billing_unit == "per m³":
        return rate / GALLONS_PER_CUBIC_METRE
    raise ValueError("Select a supported utility billing unit.")


def average_annual_rainwater_supplied(results_df: pd.DataFrame) -> float:
    required = {"Date", "DemandGallons", "UnmetDemandGallons"}
    if results_df.empty or not required.issubset(results_df.columns):
        return 0.0
    values = results_df[["Date", "DemandGallons", "UnmetDemandGallons"]].copy()
    values["Date"] = pd.to_datetime(values["Date"], errors="coerce")
    values["DemandGallons"] = pd.to_numeric(values["DemandGallons"], errors="coerce").fillna(0.0)
    values["UnmetDemandGallons"] = pd.to_numeric(
        values["UnmetDemandGallons"], errors="coerce"
    ).fillna(0.0)
    values = values.dropna(subset=["Date"])
    values["SuppliedGallons"] = (
        values["DemandGallons"].clip(lower=0.0) - values["UnmetDemandGallons"].clip(lower=0.0)
    ).clip(lower=0.0)
    annual = values.groupby(values["Date"].dt.year)["SuppliedGallons"].sum()
    return float(annual.mean()) if not annual.empty else 0.0


def average_annual_sewer_eligible_rainwater_supplied(
    results_df: pd.DataFrame,
) -> float | None:
    column = "SewerEligibleRainwaterSuppliedGallons"
    if results_df.empty or "Date" not in results_df or column not in results_df:
        return None
    values = results_df[["Date", column]].copy()
    values["Date"] = pd.to_datetime(values["Date"], errors="coerce")
    values[column] = pd.to_numeric(values[column], errors="coerce").fillna(0.0).clip(lower=0.0)
    values = values.dropna(subset=["Date"])
    annual = values.groupby(values["Date"].dt.year)[column].sum()
    return float(annual.mean()) if not annual.empty else 0.0


def calculate_financial_results(
    results_df: pd.DataFrame,
    *,
    water_rate: float,
    sewer_rate: float,
    billing_unit: str,
    sewer_eligible_percent: float,
    installed_cost: float,
    incentives: float,
    fixed_annual_maintenance: float,
    maintenance_percent: float,
    analysis_period_years: int,
) -> FinancialResults:
    supplied = average_annual_rainwater_supplied(results_df)
    sewer_eligible_supplied = average_annual_sewer_eligible_rainwater_supplied(results_df)
    return calculate_financial_results_from_annual_supply(
        supplied,
        average_annual_sewer_eligible_supplied_gallons=sewer_eligible_supplied,
        water_rate=water_rate,
        sewer_rate=sewer_rate,
        billing_unit=billing_unit,
        sewer_eligible_percent=sewer_eligible_percent,
        installed_cost=installed_cost,
        incentives=incentives,
        fixed_annual_maintenance=fixed_annual_maintenance,
        maintenance_percent=maintenance_percent,
        analysis_period_years=analysis_period_years,
    )


def calculate_financial_results_from_annual_supply(
    average_annual_supplied_gallons: float,
    *,
    average_annual_sewer_eligible_supplied_gallons: float | None = None,
    water_rate: float,
    sewer_rate: float,
    billing_unit: str,
    sewer_eligible_percent: float,
    installed_cost: float,
    incentives: float,
    fixed_annual_maintenance: float,
    maintenance_percent: float,
    analysis_period_years: int,
) -> FinancialResults:
    monetary_inputs = (installed_cost, incentives, fixed_annual_maintenance)
    if any(value < 0 for value in monetary_inputs):
        raise ValueError("Costs and incentives cannot be negative.")
    if not 0 <= sewer_eligible_percent <= 100:
        raise ValueError("Sewer-eligible supply must be between 0% and 100%.")
    if not 0 <= maintenance_percent <= 100:
        raise ValueError("Maintenance percentage must be between 0% and 100%.")
    if analysis_period_years <= 0:
        raise ValueError("Analysis period must be greater than zero.")

    if average_annual_supplied_gallons < 0:
        raise ValueError("Annual rainwater supply cannot be negative.")
    supplied = float(average_annual_supplied_gallons)
    if average_annual_sewer_eligible_supplied_gallons is None:
        sewer_eligible_supplied = supplied * sewer_eligible_percent / 100.0
    else:
        if average_annual_sewer_eligible_supplied_gallons < 0:
            raise ValueError("Annual sewer-eligible rainwater supply cannot be negative.")
        sewer_eligible_supplied = min(
            float(average_annual_sewer_eligible_supplied_gallons), supplied
        )
    water_value = supplied * tariff_rate_per_gallon(water_rate, billing_unit)
    sewer_value = (
        sewer_eligible_supplied
        * tariff_rate_per_gallon(sewer_rate, billing_unit)
    )
    gross_savings = water_value + sewer_value
    maintenance = fixed_annual_maintenance + installed_cost * maintenance_percent / 100.0
    net_savings = gross_savings - maintenance
    net_installed_cost = max(installed_cost - incentives, 0.0)
    payback = net_installed_cost / net_savings if net_savings > 0 else None
    if payback is not None and not math.isfinite(payback):
        payback = None
    net_benefit = net_savings * analysis_period_years - net_installed_cost
    return FinancialResults(
        average_annual_supplied_gallons=supplied,
        average_annual_sewer_eligible_supplied_gallons=sewer_eligible_supplied,
        annual_municipal_water_savings=water_value,
        annual_sewer_savings=sewer_value,
        gross_annual_savings=gross_savings,
        annual_maintenance_cost=maintenance,
        net_annual_savings=net_savings,
        net_installed_cost=net_installed_cost,
        simple_payback_years=payback,
        analysis_period_net_benefit=net_benefit,
    )
