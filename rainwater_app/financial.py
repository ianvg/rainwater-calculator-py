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
    average_annual_pump_energy_kwh: float
    annual_pump_energy_cost: float
    total_replacement_cost: float
    lifecycle_net_present_value: float
    internal_rate_of_return_percent: float | None
    discounted_payback_years: float | None
    annual_cash_flows: tuple[float, ...]


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


def average_annual_pump_energy(
    results_df: pd.DataFrame,
    *,
    pump_power_kw: float,
    pump_flow_rate_gallons_per_hour: float,
) -> float:
    """Calculate annual pump electricity from simulated pumped volume and rated duty."""
    if not math.isfinite(pump_power_kw) or not math.isfinite(
        pump_flow_rate_gallons_per_hour
    ):
        raise ValueError("Pump power and flow rate must be finite numbers.")
    if pump_power_kw < 0.0 or pump_flow_rate_gallons_per_hour < 0.0:
        raise ValueError("Pump power and flow rate cannot be negative.")
    if pump_power_kw == 0.0:
        return 0.0
    if pump_flow_rate_gallons_per_hour <= 0.0:
        raise ValueError("Enter a positive pump flow rate when pump power is greater than zero.")
    if results_df.empty or not {"Date", "PumpFlowGallons"}.issubset(results_df.columns):
        return 0.0
    values = results_df[["Date", "PumpFlowGallons"]].copy()
    values["Date"] = pd.to_datetime(values["Date"], errors="coerce")
    values["PumpFlowGallons"] = pd.to_numeric(
        values["PumpFlowGallons"], errors="coerce"
    ).fillna(0.0).clip(lower=0.0)
    values = values.dropna(subset=["Date"])
    annual_flow = values.groupby(values["Date"].dt.year)["PumpFlowGallons"].sum()
    average_flow = float(annual_flow.mean()) if not annual_flow.empty else 0.0
    return average_flow / pump_flow_rate_gallons_per_hour * pump_power_kw


def _npv(rate: float, cash_flows: tuple[float, ...]) -> float:
    total = cash_flows[0] if cash_flows else 0.0
    discount_factor = 1.0
    for value in cash_flows[1:]:
        discount_factor *= 1.0 + rate
        if math.isinf(discount_factor):
            continue
        total += value / discount_factor
    return total


def _irr(cash_flows: tuple[float, ...]) -> float | None:
    nonzero = [value for value in cash_flows if abs(value) > 1e-12]
    sign_changes = sum(
        (left < 0.0) != (right < 0.0)
        for left, right in zip(nonzero, nonzero[1:])
    )
    if len(nonzero) < 2 or sign_changes != 1:
        return None
    low = -0.99
    high = 1.0
    low_value = _npv(low, cash_flows)
    high_value = _npv(high, cash_flows)
    while low_value * high_value > 0.0 and high < 1_000_000.0:
        high *= 2.0
        high_value = _npv(high, cash_flows)
    if low_value * high_value > 0.0:
        return None
    for _ in range(200):
        midpoint = (low + high) / 2.0
        midpoint_value = _npv(midpoint, cash_flows)
        if abs(midpoint_value) < 1e-9:
            return midpoint
        if low_value * midpoint_value <= 0.0:
            high = midpoint
        else:
            low = midpoint
            low_value = midpoint_value
    return (low + high) / 2.0


def _discounted_payback(
    cash_flows: tuple[float, ...], discount_rate: float
) -> float | None:
    cumulative = cash_flows[0]
    if cumulative >= 0.0:
        return 0.0
    for year, cash_flow in enumerate(cash_flows[1:], start=1):
        discounted = cash_flow / ((1.0 + discount_rate) ** year)
        previous = cumulative
        cumulative += discounted
        if cumulative >= 0.0 and discounted > 0.0:
            return (year - 1) + (-previous / discounted)
    return None


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
    discount_rate_percent: float = 5.0,
    utility_rate_escalation_percent: float = 0.0,
    maintenance_escalation_percent: float = 0.0,
    electricity_rate_per_kwh: float = 0.0,
    electricity_escalation_percent: float = 0.0,
    pump_power_kw: float = 0.0,
    pump_flow_rate_gallons_per_hour: float = 0.0,
    equipment_replacement_cost: float = 0.0,
    equipment_replacement_interval_years: int = 0,
    equipment_replacement_escalation_percent: float = 0.0,
) -> FinancialResults:
    supplied = average_annual_rainwater_supplied(results_df)
    sewer_eligible_supplied = average_annual_sewer_eligible_rainwater_supplied(results_df)
    annual_pump_energy = average_annual_pump_energy(
        results_df,
        pump_power_kw=pump_power_kw,
        pump_flow_rate_gallons_per_hour=pump_flow_rate_gallons_per_hour,
    )
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
        discount_rate_percent=discount_rate_percent,
        utility_rate_escalation_percent=utility_rate_escalation_percent,
        maintenance_escalation_percent=maintenance_escalation_percent,
        average_annual_pump_energy_kwh=annual_pump_energy,
        electricity_rate_per_kwh=electricity_rate_per_kwh,
        electricity_escalation_percent=electricity_escalation_percent,
        equipment_replacement_cost=equipment_replacement_cost,
        equipment_replacement_interval_years=equipment_replacement_interval_years,
        equipment_replacement_escalation_percent=(
            equipment_replacement_escalation_percent
        ),
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
    discount_rate_percent: float = 5.0,
    utility_rate_escalation_percent: float = 0.0,
    maintenance_escalation_percent: float = 0.0,
    average_annual_pump_energy_kwh: float = 0.0,
    electricity_rate_per_kwh: float = 0.0,
    electricity_escalation_percent: float = 0.0,
    equipment_replacement_cost: float = 0.0,
    equipment_replacement_interval_years: int = 0,
    equipment_replacement_escalation_percent: float = 0.0,
) -> FinancialResults:
    monetary_inputs = (
        installed_cost,
        incentives,
        fixed_annual_maintenance,
        electricity_rate_per_kwh,
        equipment_replacement_cost,
    )
    numeric_inputs = monetary_inputs + (
        water_rate,
        sewer_rate,
        average_annual_supplied_gallons,
        sewer_eligible_percent,
        maintenance_percent,
        average_annual_pump_energy_kwh,
        discount_rate_percent,
        utility_rate_escalation_percent,
        maintenance_escalation_percent,
        electricity_escalation_percent,
        equipment_replacement_escalation_percent,
    )
    if any(not math.isfinite(float(value)) for value in numeric_inputs):
        raise ValueError("Financial inputs must be finite numbers.")
    if any(value < 0 for value in monetary_inputs):
        raise ValueError("Costs and incentives cannot be negative.")
    if not 0 <= sewer_eligible_percent <= 100:
        raise ValueError("Sewer-eligible supply must be between 0% and 100%.")
    if not 0 <= maintenance_percent <= 100:
        raise ValueError("Maintenance percentage must be between 0% and 100%.")
    if analysis_period_years <= 0:
        raise ValueError("Analysis period must be greater than zero.")
    if equipment_replacement_interval_years < 0:
        raise ValueError("Equipment replacement interval cannot be negative.")
    if equipment_replacement_cost > 0.0 and equipment_replacement_interval_years <= 0:
        raise ValueError(
            "Enter a positive equipment replacement interval when replacement cost is greater than zero."
        )
    if average_annual_pump_energy_kwh < 0.0:
        raise ValueError("Annual pump energy cannot be negative.")
    if discount_rate_percent < 0.0:
        raise ValueError("Discount rate cannot be negative.")
    escalation_rates = (
        utility_rate_escalation_percent,
        maintenance_escalation_percent,
        electricity_escalation_percent,
        equipment_replacement_escalation_percent,
    )
    if any(rate <= -100.0 for rate in escalation_rates):
        raise ValueError("Escalation rates must be greater than -100%.")

    if average_annual_supplied_gallons < 0:
        raise ValueError("Annual rainwater supply cannot be negative.")
    supplied = float(average_annual_supplied_gallons)
    if average_annual_sewer_eligible_supplied_gallons is None:
        sewer_eligible_supplied = supplied * sewer_eligible_percent / 100.0
    else:
        if not math.isfinite(float(average_annual_sewer_eligible_supplied_gallons)):
            raise ValueError("Annual sewer-eligible rainwater supply must be finite.")
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
    annual_energy_cost = average_annual_pump_energy_kwh * electricity_rate_per_kwh
    net_savings = gross_savings - maintenance - annual_energy_cost
    net_installed_cost = max(installed_cost - incentives, 0.0)
    payback = net_installed_cost / net_savings if net_savings > 0 else None
    if payback is not None and not math.isfinite(payback):
        payback = None
    discount_rate = discount_rate_percent / 100.0
    utility_escalation = utility_rate_escalation_percent / 100.0
    maintenance_escalation = maintenance_escalation_percent / 100.0
    electricity_escalation = electricity_escalation_percent / 100.0
    replacement_escalation = equipment_replacement_escalation_percent / 100.0
    annual_cash_flows = [-net_installed_cost]
    replacement_total = 0.0
    for year in range(1, analysis_period_years + 1):
        utility_savings = gross_savings * ((1.0 + utility_escalation) ** (year - 1))
        maintenance_cost = maintenance * ((1.0 + maintenance_escalation) ** (year - 1))
        energy_cost = annual_energy_cost * ((1.0 + electricity_escalation) ** (year - 1))
        replacement = (
            equipment_replacement_cost * ((1.0 + replacement_escalation) ** (year - 1))
            if equipment_replacement_interval_years > 0
            and year < analysis_period_years
            and year % equipment_replacement_interval_years == 0
            else 0.0
        )
        replacement_total += replacement
        annual_cash_flows.append(
            utility_savings - maintenance_cost - energy_cost - replacement
        )
    cash_flows = tuple(annual_cash_flows)
    net_benefit = sum(cash_flows)
    lifecycle_npv = _npv(discount_rate, cash_flows)
    irr = _irr(cash_flows)
    discounted_payback = _discounted_payback(cash_flows, discount_rate)
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
        average_annual_pump_energy_kwh=average_annual_pump_energy_kwh,
        annual_pump_energy_cost=annual_energy_cost,
        total_replacement_cost=replacement_total,
        lifecycle_net_present_value=lifecycle_npv,
        internal_rate_of_return_percent=irr * 100.0 if irr is not None else None,
        discounted_payback_years=discounted_payback,
        annual_cash_flows=cash_flows,
    )
