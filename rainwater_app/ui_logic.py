"""Pure validation and conversion helpers shared by user interfaces.

This module intentionally has no Tkinter imports.  Keeping staged form logic
here makes it independently testable and prevents the desktop window class from
becoming the owner of domain-adjacent validation rules.
"""

from __future__ import annotations

import math

from rainwater_app.models import DemandObject, MONTH_KEYS, WEEKDAY_KEYS
from rainwater_app.units import LITERS_PER_GALLON


def demand_flow_to_gallons_per_minute(value: float, unit: str) -> float:
    if unit == "gpm":
        return value
    if unit == "gal/hr":
        return value / 60.0
    if unit == "lpm":
        return value / LITERS_PER_GALLON
    if unit == "liter/hr":
        return value / (LITERS_PER_GALLON * 60.0)
    raise ValueError(f"Unsupported demand flow unit: {unit}")


def demand_flow_from_gallons_per_minute(value: float, unit: str) -> float:
    if unit == "gpm":
        return value
    if unit == "gal/hr":
        return value * 60.0
    if unit == "lpm":
        return value * LITERS_PER_GALLON
    if unit == "liter/hr":
        return value * LITERS_PER_GALLON * 60.0
    raise ValueError(f"Unsupported demand flow unit: {unit}")


def normalized_demand_object_indices(value: object, demand_object_count: int) -> list[int]:
    if not isinstance(value, list):
        return []
    normalized: list[int] = []
    for raw_index in value:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < demand_object_count and index not in normalized:
            normalized.append(index)
    return normalized


def validated_schedule_library(payload: object) -> dict[str, dict[str, list[float]]]:
    if not isinstance(payload, dict):
        return {}
    library: dict[str, dict[str, list[float]]] = {}
    for raw_name, raw_schedule in payload.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_schedule, dict):
            continue
        schedule: dict[str, list[float]] = {}
        valid = True
        for day in WEEKDAY_KEYS:
            raw_values = raw_schedule.get(day)
            if not isinstance(raw_values, list) or len(raw_values) != 24:
                valid = False
                break
            try:
                values = [min(max(float(value), 0.0), 1.0) for value in raw_values]
            except (TypeError, ValueError):
                valid = False
                break
            schedule[day] = values
        if valid:
            library[name] = schedule
    return library


def common_demand_object_templates() -> dict[str, DemandObject]:
    monthly_types = (
        ("Ice making", "Ice making"),
        ("Cooling tower", "Cooling tower"),
        ("Ice skating", "Ice skating"),
        ("Other indoor", "Other indoor"),
        ("Spray irrigation", "Irrigation system"),
        ("Drip irrigation", "Irrigation system"),
        ("Vehicle washing", "Vehicle washing"),
        ("Other outdoor", "Other outdoor"),
    )
    templates = {
        "Simple recurring demand": DemandObject(
            "Simple recurring demand", "Other", demand_mode="recurring_daily"
        ),
        "Toilet": DemandObject("Toilet", "Toilet", 3.0),
        "Urinal": DemandObject("Urinal", "Urinal", 1.0),
    }
    templates.update(
        {
            name: DemandObject(name, object_type, demand_mode="monthly_volume")
            for name, object_type in monthly_types
        }
    )
    return templates


def _float_or_default(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def validated_demand_object_library(payload: object) -> dict[str, DemandObject]:
    if not isinstance(payload, dict):
        return {}
    library: dict[str, DemandObject] = {}
    for raw_name, raw_object in payload.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_object, dict):
            continue
        try:
            flow = max(
                float(raw_object.get("instantaneous_demand_gallons_per_minute", 0.0)),
                0.0,
            )
        except (TypeError, ValueError):
            continue
        library[name] = DemandObject(
            name=name,
            object_type=str(raw_object.get("object_type", "Other")),
            instantaneous_demand_gallons_per_minute=flow,
            demand_mode=str(raw_object.get("demand_mode", "scheduled_flow")),
            recurring_daily_gallons=max(
                _float_or_default(raw_object.get("recurring_daily_gallons")), 0.0
            ),
            operating_days_per_week=min(
                max(
                    int(_float_or_default(raw_object.get("operating_days_per_week"), 7)),
                    0,
                ),
                7,
            ),
            operating_weekdays=(
                [int(day) for day in raw_object.get("operating_weekdays", [])]
                if isinstance(raw_object.get("operating_weekdays"), list)
                else None
            ),
            monthly_daily_demand_gallons={
                month: max(
                    _float_or_default(
                        dict(raw_object.get("monthly_daily_demand_gallons", {})).get(month)
                    ),
                    0.0,
                )
                for month in MONTH_KEYS
            },
            monthly_demand_gallons={
                month: max(
                    _float_or_default(
                        dict(raw_object.get("monthly_demand_gallons", {})).get(month)
                    ),
                    0.0,
                )
                for month in MONTH_KEYS
            },
            sewer_eligible=raw_object.get("sewer_eligible"),
        )
    return library


def antecedent_dry_period_to_days(value: float, unit: str) -> float:
    return value / 24.0 if unit.casefold() == "hours" else value


def antecedent_dry_period_from_days(days: float, unit: str) -> float:
    return days * 24.0 if unit.casefold() == "hours" else days


def system_object_editor_validation(
    component_type: str, values: dict[str, object]
) -> list[str]:
    """Return user-facing validation errors for a staged system-object edit."""
    errors: list[str] = []
    if not str(values.get("name", "")).strip():
        errors.append("Name cannot be blank.")

    numeric_labels = {
        "selected_tank_size": "Primary tank size",
        "initial_fill": "Initial fill",
        "reserve": "Minimum operating level",
        "graph_start": "Graph start tank size",
        "graph_end": "Graph end tank size",
        "graph_step": "Graph step",
        "graph_auto_step_count": "Number of steps",
        "filtration_pump_capacity": "Pump capacity",
        "filter_recovery": "Filter recovery",
        "booster_tank_size": "Tank size",
        "booster_initial_fill": "Initial fill",
        "booster_refill_level": "Refill level",
        "pump_capacity": "Pump capacity",
    }
    fields_by_type = {
        "primary_tank": (
            "selected_tank_size",
            "initial_fill",
            "reserve",
            "graph_start",
            "graph_end",
            "graph_step",
            "graph_auto_step_count",
        ),
        "filtration_pump": ("filtration_pump_capacity",),
        "filtration_system": ("filter_recovery",),
        "booster_tank": (
            "booster_tank_size",
            "booster_initial_fill",
            "booster_refill_level",
        ),
        "booster_pump": ("pump_capacity",),
    }
    parsed: dict[str, float] = {}
    for field in fields_by_type.get(component_type, ()):
        raw = str(values.get(field, "")).strip().replace(",", "")
        try:
            number = float(raw)
            if not math.isfinite(number):
                raise ValueError
            parsed[field] = number
        except ValueError:
            errors.append(f"{numeric_labels[field]} must be a valid number.")

    if errors:
        return errors

    for field in {"filtration_pump_capacity", "booster_tank_size", "pump_capacity"}.intersection(parsed):
        if parsed[field] < 0:
            errors.append(f"{numeric_labels[field]} cannot be negative.")

    for field in (
        "initial_fill",
        "reserve",
        "filter_recovery",
        "booster_initial_fill",
        "booster_refill_level",
    ):
        if field in parsed and not 0 <= parsed[field] <= 100:
            errors.append(f"{numeric_labels[field]} must be between 0 and 100%.")

    if component_type == "primary_tank":
        if parsed["selected_tank_size"] <= 0:
            errors.append("Primary tank size must be greater than zero.")
        if parsed["graph_start"] <= 0:
            errors.append("Graph start tank size must be greater than zero.")
        if parsed["graph_end"] <= parsed["graph_start"]:
            errors.append("Graph end tank size must be greater than graph start tank size.")
        if parsed["graph_step"] <= 0:
            errors.append("Graph step must be greater than zero.")
        elif parsed["graph_end"] > parsed["graph_start"] and parsed["graph_step"] > (
            parsed["graph_end"] - parsed["graph_start"]
        ):
            errors.append("Graph step cannot exceed the graph range.")
        step_count = parsed["graph_auto_step_count"]
        if not step_count.is_integer() or not 1 <= step_count <= 1000:
            errors.append("Number of steps must be a whole number from 1 to 1000.")

    return errors


def parse_coordinates(
    latitude_text: str, longitude_text: str
) -> tuple[float | None, float | None]:
    latitude_value = latitude_text.strip()
    longitude_value = longitude_text.strip()
    if not latitude_value and not longitude_value:
        return None, None
    if not latitude_value or not longitude_value:
        raise ValueError("Enter both latitude and longitude, or leave both fields blank.")
    try:
        latitude = float(latitude_value)
        longitude = float(longitude_value)
    except ValueError as exc:
        raise ValueError("Latitude and longitude must be numbers.") from exc
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90 degrees.")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180 degrees.")
    return latitude, longitude


def state_code(value: str) -> str:
    return value.split(" - ", 1)[0].strip().upper()


def safe_project_file_name(name: str) -> str:
    safe = "".join(
        char if char.isalnum() or char in " ._-" else "_" for char in name
    ).strip()
    return f"{safe or 'rainwater_project'}.db"
