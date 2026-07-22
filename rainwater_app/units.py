from __future__ import annotations

from .models import METRIC_UNIT_SYSTEM, ProjectConfig, normalize_unit_system

SQFT_PER_SQM = 10.7639
LITERS_PER_GALLON = 3.78541
MM_PER_INCH = 25.4


def is_metric(config: ProjectConfig) -> bool:
    return normalize_unit_system(config.unit_system) == METRIC_UNIT_SYSTEM


def area_unit(config: ProjectConfig) -> str:
    return "m^2" if is_metric(config) else "sq ft"


def volume_unit(config: ProjectConfig) -> str:
    return "L" if is_metric(config) else "gal"


def precip_unit(config: ProjectConfig) -> str:
    return "mm" if is_metric(config) else "in"


def area_to_display(value_sqft: float, config: ProjectConfig) -> float:
    return value_sqft / SQFT_PER_SQM if is_metric(config) else value_sqft


def area_to_internal(value: float, config: ProjectConfig) -> float:
    return value * SQFT_PER_SQM if is_metric(config) else value


def volume_to_display(value_gallons: float, config: ProjectConfig) -> float:
    return value_gallons * LITERS_PER_GALLON if is_metric(config) else value_gallons


def volume_to_internal(value: float, config: ProjectConfig) -> float:
    return value / LITERS_PER_GALLON if is_metric(config) else value


def precip_to_display(value_inches: float, config: ProjectConfig) -> float:
    return value_inches * MM_PER_INCH if is_metric(config) else value_inches


def precip_to_internal(value: float, config: ProjectConfig) -> float:
    return value / MM_PER_INCH if is_metric(config) else value
