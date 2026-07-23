"""UI-independent preparation of chart series, labels, and tabular equivalents."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from .models import ProjectConfig
from .number_formatting import format_number
from .reporting import report_tank_level_distribution, yearly_demand_reliability
from .units import volume_to_display, volume_unit


def chart_render_indices(y_values: list[float], max_points: int) -> list[int]:
    """Downsample a line while retaining endpoints and each bucket's extrema."""
    point_count = len(y_values)
    if point_count <= max_points:
        return list(range(point_count))

    bucket_count = max((max_points - 2) // 2, 1)
    interior_count = point_count - 2
    bucket_size = max((interior_count + bucket_count - 1) // bucket_count, 1)
    indices = [0]
    for start in range(1, point_count - 1, bucket_size):
        stop = min(start + bucket_size, point_count - 1)
        bucket = range(start, stop)
        low = min(bucket, key=y_values.__getitem__)
        high = max(bucket, key=y_values.__getitem__)
        indices.extend(sorted({low, high}))
    indices.append(point_count - 1)
    return indices


def reliability_curve_chart_data(
    curve: pd.DataFrame, config: ProjectConfig
) -> dict[str, object]:
    unit = volume_unit(config)
    if curve.empty or not {"TankSizeGallons", "ReliabilityPercent"}.issubset(curve.columns):
        rows: list[dict[str, float]] = []
    else:
        rows = [
            {
                "tank_size": volume_to_display(float(tank_size), config),
                "reliability": float(reliability),
            }
            for tank_size, reliability in zip(
                curve["TankSizeGallons"], curve["ReliabilityPercent"]
            )
        ]
    return {
        "title": f"Reliability vs Tank Size ({unit})",
        "x_label": f"Tank size ({unit})",
        "y_label": "Reliability %",
        "rows": rows,
        "x_values": [float(row["tank_size"]) for row in rows],
        "y_values": [float(row["reliability"]) for row in rows],
        "hover_labels": [
            f'Tank size: {format_number(row["tank_size"], config, max_decimal_places=0)} {unit}\n'
            f'Reliability: {format_number(row["reliability"], config)}%'
            for row in rows
        ],
    }


def tank_level_distribution_chart_data(
    results: pd.DataFrame, config: ProjectConfig, bin_count: int = 6
) -> dict[str, object]:
    capacity = volume_to_display(config.selected_tank_size_gal, config)
    unit = volume_unit(config)
    return {
        "title": (
            f"Tank Level Distribution - "
            f"{format_number(capacity, config, max_decimal_places=0)} {unit} tank"
        ),
        "x_label": f"Tank level range ({unit})",
        "y_label": "Days",
        "capacity": capacity,
        "unit": unit,
        "rows": report_tank_level_distribution(results, config, bin_count),
    }


def yearly_reliability_chart_data(
    results: pd.DataFrame, config: ProjectConfig
) -> dict[str, object]:
    capacity = volume_to_display(config.selected_tank_size_gal, config)
    unit = volume_unit(config)
    reliability = (
        float(results["ReliabilityPercent"].iloc[0])
        if not results.empty and "ReliabilityPercent" in results
        else 0.0
    )
    return {
        "title": (
            f"Yearly Demand Reliability - "
            f"{format_number(capacity, config, max_decimal_places=0)} {unit} tank"
        ),
        "x_label": "Year",
        "y_label": "Days (%)",
        "selected_reliability": reliability,
        "rows": yearly_demand_reliability(results),
    }


def multitank_chart_data(
    comparison_results: Mapping[float, pd.DataFrame], config: ProjectConfig
) -> dict[str, object]:
    """Prepare shared screen and report series for every comparison tank."""
    unit = volume_unit(config)
    tank_series: list[dict[str, object]] = []
    distribution_series: list[dict[str, object]] = []
    yearly_series: list[dict[str, object]] = []
    yearly_stacked_charts: list[dict[str, object]] = []

    for tank_size, results in sorted(comparison_results.items()):
        if results.empty or "WaterInTankGallons" not in results:
            continue
        display_size = volume_to_display(float(tank_size), config)
        label = f"{format_number(display_size, config, max_decimal_places=0)} {unit}"
        levels_internal = [float(value) for value in results["WaterInTankGallons"]]
        levels = [volume_to_display(value, config) for value in levels_internal]
        dates = pd.to_datetime(
            results.get("Date", pd.Series(pd.NaT, index=results.index)), errors="coerce"
        )
        sampled = chart_render_indices(levels, 800)
        yearly_points: dict[str, list[tuple[float, float]]] = {}
        for year in sorted(int(value) for value in dates.dropna().dt.year.unique()):
            mask = dates.dt.year == year
            year_levels = [
                volume_to_display(float(value), config)
                for value in results.loc[mask, "WaterInTankGallons"]
            ]
            year_indices = chart_render_indices(year_levels, 400)
            yearly_points[str(year)] = [
                (float(index + 1), year_levels[index]) for index in year_indices
            ]
        tank_series.append(
            {
                "label": label,
                "x_values": [float(index) for index in range(len(levels))],
                "y_values": levels,
                "points": [(float(index), levels[index]) for index in sampled],
                "yearly_points": yearly_points,
                "dated_points": [
                    (dates.iloc[index].strftime("%Y-%m-%d"), levels[index])
                    for index in sampled
                    if not pd.isna(dates.iloc[index])
                ],
            }
        )

        percentages = [
            min(max(value / float(tank_size) * 100.0, 0.0), 100.0)
            if tank_size > 0.0
            else 0.0
            for value in levels_internal
        ]
        counts = [0] * 6
        for percentage in percentages:
            counts[min(int(percentage / (100.0 / 6)), 5)] += 1
        total = len(percentages) or 1
        distribution_x = [(index + 0.5) * (100.0 / 6) for index in range(6)]
        distribution_y = [count / total * 100.0 for count in counts]
        distribution_series.append(
            {
                "label": label,
                "x_values": distribution_x,
                "y_values": distribution_y,
                "points": list(zip(distribution_x, distribution_y)),
            }
        )

        yearly = yearly_demand_reliability(results)
        yearly_x = [float(row["year"]) for row in yearly]
        yearly_y = [float(row["met_percent"]) for row in yearly]
        yearly_series.append(
            {
                "label": label,
                "x_values": yearly_x,
                "y_values": yearly_y,
                "points": list(zip(yearly_x, yearly_y)),
            }
        )
        yearly_stacked_charts.append(
            {
                "type": "yearly_stacked",
                "title": f"Yearly Demand Reliability - {label} tank",
                "yearly_reliability": yearly,
                "selected_reliability": (
                    float(results["ReliabilityPercent"].iloc[0])
                    if "ReliabilityPercent" in results
                    else 0.0
                ),
            }
        )

    report_charts = [
        {
            "title": "Tank level distribution - multitank",
            "x_label": "Tank level (% of capacity)",
            "y_label": "Days (%)",
            "series": [
                {"label": row["label"], "points": row["points"]}
                for row in distribution_series
            ],
        },
        {
            "title": "Yearly demand reliability - multitank",
            "x_label": "Year",
            "y_label": "Demand met (%)",
            "series": [
                {"label": row["label"], "points": row["points"]}
                for row in yearly_series
            ],
            "interactive_series_toggle": True,
        },
        *yearly_stacked_charts,
        {
            "type": "tank_history",
            "title": f"Tank Water Over Time ({unit})",
            "x_label": "Day of year",
            "y_label": unit,
            "series": [
                {
                    "label": row["label"],
                    "points": row["points"],
                    "yearly_points": row["yearly_points"],
                    "dated_points": row["dated_points"],
                }
                for row in tank_series
            ],
        },
    ]
    return {
        "unit": unit,
        "tank_series": tank_series,
        "distribution_series": distribution_series,
        "yearly_series": yearly_series,
        "report_charts": report_charts,
    }
