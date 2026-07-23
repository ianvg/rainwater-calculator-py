import pandas as pd
import pytest

from rainwater_app.chart_data import (
    chart_render_indices,
    multitank_chart_data,
    reliability_curve_chart_data,
    tank_level_distribution_chart_data,
    yearly_reliability_chart_data,
)
from rainwater_app.defaults import default_project_config


def test_chart_render_indices_limit_points_and_preserve_extrema() -> None:
    values = [float(index % 100) for index in range(10_000)]
    values[4_321] = -50.0
    values[7_654] = 250.0

    indices = chart_render_indices(values, max_points=600)

    assert indices == sorted(set(indices))
    assert len(indices) <= 600
    assert indices[0] == 0
    assert indices[-1] == len(values) - 1
    assert 4_321 in indices
    assert 7_654 in indices


def test_selected_tank_chart_data_reuses_report_rows_and_project_units() -> None:
    config = default_project_config()
    config.unit_system = "Metric"
    config.selected_tank_size_gal = 600.0
    curve = pd.DataFrame(
        {"TankSizeGallons": [500.0, 600.0], "ReliabilityPercent": [75.0, 80.0]}
    )
    results = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "WaterInTankGallons": [0.0, 600.0],
            "DemandMet": [True, False],
            "ReliabilityPercent": [50.0, 50.0],
        }
    )

    reliability = reliability_curve_chart_data(curve, config)
    distribution = tank_level_distribution_chart_data(results, config)
    yearly = yearly_reliability_chart_data(results, config)

    assert reliability["x_label"] == "Tank size (L)"
    assert reliability["x_values"] == pytest.approx([1_892.705, 2_271.246])
    assert distribution["unit"] == "L"
    assert sum(row["count"] for row in distribution["rows"]) == 2
    assert yearly["rows"][0]["met_percent"] == 50.0
    assert yearly["selected_reliability"] == 50.0


def test_multitank_chart_data_keeps_screen_and_report_series_in_parity() -> None:
    config = default_project_config()
    dates = pd.date_range("2024-12-31", periods=3, freq="D")
    results = pd.DataFrame(
        {
            "Date": dates,
            "WaterInTankGallons": [0.0, 250.0, 500.0],
            "DemandMet": [True, False, True],
            "ReliabilityPercent": [2 / 3 * 100.0] * 3,
        }
    )

    prepared = multitank_chart_data({500.0: results}, config)

    tank = prepared["tank_series"][0]
    assert tank["label"] == "500 gal"
    assert tank["y_values"] == [0.0, 250.0, 500.0]
    assert tank["yearly_points"].keys() == {"2024", "2025"}
    assert tank["dated_points"][0] == ("2024-12-31", 0.0)
    distribution = prepared["distribution_series"][0]
    assert sum(distribution["y_values"]) == pytest.approx(100.0)
    report_distribution = prepared["report_charts"][0]["series"][0]
    assert report_distribution["points"] == distribution["points"]
    report_history = prepared["report_charts"][-1]["series"][0]
    assert report_history["points"] == tank["points"]
