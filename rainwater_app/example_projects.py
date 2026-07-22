"""Built-in, self-contained projects for learning the application workflow."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .analysis_service import AnalysisOutcome, AnalysisService
from .analysis_state import analysis_input_signature
from .defaults import default_project_config
from .models import (
    ENGLISH_UNIT_SYSTEM,
    METRIC_UNIT_SYSTEM,
    FRACTIONAL_SCHEDULE_TYPE,
    DemandObject,
    MONTH_KEYS,
    ProjectConfig,
    Surface,
    WEEKDAY_KEYS,
)


@dataclass(frozen=True)
class CompletedExampleProject:
    """Inputs and completed analysis data for a built-in example."""

    config: ProjectConfig
    rainfall: pd.DataFrame
    outcome: AnalysisOutcome


EXAMPLE_PROJECT_LABELS = {
    "home_garden": "Home and garden (Metric)",
    "small_office": "Small office (English)",
}


def _daily_rainfall(*, multiplier: float = 1.0) -> pd.DataFrame:
    """Return a deterministic three-year daily rainfall record in internal inches."""
    dates = pd.date_range("2021-01-01", "2023-12-31", freq="D")
    precipitation: list[float] = []
    for index, date in enumerate(dates):
        seasonal = 0.85 + 0.25 * (1.0 - abs(date.month - 7) / 6.0)
        amount = 0.0
        if index % 7 == 0:
            amount += 0.18 * seasonal
        if index % 19 == 4:
            amount += 0.62 * seasonal
        if index % 31 == 11:
            amount += 1.05 * seasonal
        precipitation.append(round(amount * multiplier, 3))
    return pd.DataFrame({"Date": dates, "Precipitation": precipitation})


def _schedule(*, weekdays_only: bool) -> dict[str, list[float]]:
    return {
        day: (
            [0.0] * 6 + [1.0] * 17 + [0.0]
            if not weekdays_only or day in WEEKDAY_KEYS[:5]
            else [0.0] * 24
        )
        for day in WEEKDAY_KEYS
    }


def _home_and_garden() -> tuple[ProjectConfig, pd.DataFrame]:
    config = default_project_config("Example - Home and garden")
    config.unit_system = METRIC_UNIT_SYSTEM
    config.country_code = "CAN"
    config.city = "Guelph"
    config.state_or_province = "Ontario"
    config.notes = (
        "Built-in example: a detached home supplying toilets and seasonal garden "
        "irrigation. Inputs and completed results are provided for exploration."
    )
    config.surfaces = [
        Surface("House metal roof", 1_800.0, 0.95, 0.02),
        Surface("Garage asphalt roof", 480.0, 0.90, 0.02),
    ]
    schedule_name = "Daily household use"
    config.demand.hourly_schedule_library = {
        schedule_name: _schedule(weekdays_only=False)
    }
    config.demand.hourly_schedule_types = {
        schedule_name: FRACTIONAL_SCHEDULE_TYPE
    }
    config.demand.active_hourly_schedule_name = schedule_name
    irrigation = {month: 0.0 for month in MONTH_KEYS}
    irrigation.update({"may": 450.0, "jun": 900.0, "jul": 1_200.0, "aug": 1_000.0, "sep": 400.0})
    config.demand.demand_objects = [
        DemandObject(
            "Toilet flushing",
            "Toilet",
            schedule_name=schedule_name,
            demand_mode="recurring_daily",
            recurring_daily_gallons=32.0,
        ),
        DemandObject(
            "Garden irrigation",
            "Irrigation system",
            schedule_name=schedule_name,
            demand_mode="monthly_volume",
            monthly_demand_gallons=irrigation,
            sewer_eligible=False,
        ),
    ]
    config.graph_start_gal = 250
    config.graph_end_gal = 2_500
    config.graph_step_gal = 250
    config.selected_tank_size_gal = 1_000.0
    config.financial_parameters.currency = "CAD"
    config.financial_parameters.water_rate = 4.25
    config.financial_parameters.sewer_rate = 3.10
    config.rainfall_source_label = "built-in representative daily rainfall"
    return config, _daily_rainfall()


def _small_office() -> tuple[ProjectConfig, pd.DataFrame]:
    config = default_project_config("Example - Small office")
    config.unit_system = ENGLISH_UNIT_SYSTEM
    config.country_code = "USA"
    config.city = "Raleigh"
    config.state_or_province = "North Carolina"
    config.notes = (
        "Built-in example: a small weekday office supplying toilet fixtures and "
        "landscape irrigation. Inputs and completed results are provided for exploration."
    )
    config.surfaces = [
        Surface("Office membrane roof", 12_000.0, 0.95, 0.03),
        Surface("Covered parking", 3_500.0, 0.85, 0.03),
    ]
    schedule_name = "Office weekdays"
    config.demand.hourly_schedule_library = {
        schedule_name: _schedule(weekdays_only=True)
    }
    config.demand.hourly_schedule_types = {
        schedule_name: FRACTIONAL_SCHEDULE_TYPE
    }
    config.demand.active_hourly_schedule_name = schedule_name
    irrigation = {month: 0.0 for month in MONTH_KEYS}
    irrigation.update({"apr": 2_000.0, "may": 4_000.0, "jun": 6_000.0, "jul": 7_500.0, "aug": 6_500.0, "sep": 3_500.0, "oct": 1_500.0})
    config.demand.demand_objects = [
        DemandObject(
            "Restroom fixtures",
            "Toilet",
            schedule_name=schedule_name,
            demand_mode="recurring_daily",
            recurring_daily_gallons=260.0,
            operating_days_per_week=5,
        ),
        DemandObject(
            "Landscape irrigation",
            "Irrigation system",
            schedule_name=schedule_name,
            demand_mode="monthly_volume",
            monthly_demand_gallons=irrigation,
            sewer_eligible=False,
        ),
    ]
    config.graph_start_gal = 2_500
    config.graph_end_gal = 20_000
    config.graph_step_gal = 2_500
    config.selected_tank_size_gal = 10_000.0
    config.financial_parameters.water_rate = 8.50
    config.financial_parameters.sewer_rate = 6.25
    config.financial_parameters.installed_cost = 48_000.0
    config.rainfall_source_label = "built-in representative daily rainfall"
    return config, _daily_rainfall(multiplier=1.15)


def build_completed_example(example_id: str) -> CompletedExampleProject:
    """Build a fresh example and run its complete single-tank analysis."""
    builders = {
        "home_garden": _home_and_garden,
        "small_office": _small_office,
    }
    try:
        config, rainfall = builders[example_id]()
    except KeyError as exc:
        raise ValueError(f"Unknown example project: {example_id}") from exc
    outcome = AnalysisService().run(config, rainfall)
    config.analysis_input_signature = analysis_input_signature(config, rainfall)
    config.analysis_unit_system = config.unit_system
    return CompletedExampleProject(config, rainfall, outcome)
