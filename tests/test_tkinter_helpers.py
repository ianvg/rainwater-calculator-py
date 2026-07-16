import pandas as pd
import pytest
from pypdf import PdfReader

from rainwater_app.defaults import default_project_config
from rainwater_app.models import Surface
from tkinter_app import (
    RainwaterTkApp,
    _demand_flow_from_gallons_per_minute,
    _demand_flow_to_gallons_per_minute,
    _normalized_demand_object_indices,
    _parse_coordinates,
    _validated_demand_object_library,
    _validated_schedule_library,
    _report_average_annual_precipitation,
    _report_demand_summary,
    _report_surface_rows,
    _report_tank_level_distribution,
    _yearly_demand_reliability,
)


@pytest.mark.parametrize(
    ("unit", "display_value"),
    [("gpm", 2.0), ("gal/hr", 120.0), ("lpm", 7.57082), ("liter/hr", 454.2492)],
)
def test_demand_flow_units_round_trip(unit: str, display_value: float) -> None:
    assert _demand_flow_from_gallons_per_minute(2.0, unit) == pytest.approx(display_value)
    assert _demand_flow_to_gallons_per_minute(display_value, unit) == pytest.approx(2.0)


def test_demand_object_assignments_drop_invalid_and_duplicate_indices() -> None:
    assert _normalized_demand_object_indices([2, "0", 2, -1, 4, "bad"], 3) == [2, 0]


def test_custom_demand_object_library_validation() -> None:
    result = _validated_demand_object_library(
        {
            " Irrigation ": {
                "object_type": "Irrigation system",
                "instantaneous_demand_gallons_per_minute": 12.5,
            },
            "Invalid": {"instantaneous_demand_gallons_per_minute": "bad"},
        }
    )

    assert list(result) == ["Irrigation"]
    assert result["Irrigation"].object_type == "Irrigation system"
    assert result["Irrigation"].instantaneous_demand_gallons_per_minute == 12.5


def test_custom_schedule_library_validation_keeps_complete_weekly_profiles() -> None:
    valid_schedule = {day: [1.0 / 24.0] * 24 for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}

    result = _validated_schedule_library(
        {
            " Office hours ": valid_schedule,
            "Incomplete": {"mon": [1.0] * 24},
            "Invalid": {**valid_schedule, "fri": ["bad"] * 24},
        }
    )

    assert list(result) == ["Office hours"]
    assert len(result["Office hours"]["sun"]) == 24


def test_parse_coordinates_accepts_blank_or_valid_pairs() -> None:
    assert _parse_coordinates("", "") == (None, None)
    assert _parse_coordinates("36.548921", "-82.456789") == (36.548921, -82.456789)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [("36", ""), ("north", "-82"), ("91", "0"), ("0", "-181")],
)
def test_parse_coordinates_rejects_incomplete_or_invalid_pairs(latitude: str, longitude: str) -> None:
    with pytest.raises(ValueError):
        _parse_coordinates(latitude, longitude)


def test_station_coordinates_accept_valid_values_and_reject_missing_or_invalid_values() -> None:
    assert RainwaterTkApp._station_coordinates({"latitude": "43.65", "longitude": "-79.38"}) == (
        43.65,
        -79.38,
    )
    assert RainwaterTkApp._station_coordinates({"latitude": None, "longitude": -79.38}) is None
    assert RainwaterTkApp._station_coordinates({"latitude": 91, "longitude": 0}) is None


def test_station_clustering_groups_nearby_stations_only_at_low_zoom() -> None:
    stations = [
        {"latitude": 33.7490, "longitude": -84.3880},
        {"latitude": 33.7550, "longitude": -84.3800},
        {"latitude": 32.0809, "longitude": -81.0912},
    ]

    low_zoom_clusters = RainwaterTkApp._cluster_stations(stations, zoom=5)
    high_zoom_clusters = RainwaterTkApp._cluster_stations(stations, zoom=14)

    assert sorted(len(cluster) for cluster in low_zoom_clusters) == [1, 2]
    assert sorted(len(cluster) for cluster in high_zoom_clusters) == [1, 1, 1]


def test_chart_render_indices_limit_points_and_preserve_extrema() -> None:
    values = [float(index % 100) for index in range(10_000)]
    values[4_321] = -50.0
    values[7_654] = 250.0

    indices = RainwaterTkApp._chart_render_indices(values, max_points=600)

    assert indices == sorted(set(indices))
    assert len(indices) <= 600
    assert indices[0] == 0
    assert indices[-1] == len(values) - 1
    assert 4_321 in indices
    assert 7_654 in indices


def test_acis_station_label_includes_state_name() -> None:
    label = RainwaterTkApp._station_label(
        {"name": "Central Park", "sid": "123", "state": "NY", "provider": "ACIS"}
    )

    assert label == "Central Park - 123 in New York"


def test_eccc_station_label_includes_province_name() -> None:
    label = RainwaterTkApp._station_label(
        {"name": "Toronto", "sid": "456", "state": "ON", "provider": "ECCC"}
    )

    assert label == "Toronto - 456 in Ontario"


def test_report_surfaces_only_include_positive_areas() -> None:
    config = default_project_config()
    config.surfaces = [
        Surface("Used roof", area=1000.0, runoff_coefficient=0.9),
        Surface("Unused roof", area=0.0, runoff_coefficient=0.95),
        Surface("Invalid negative roof", area=-10.0, runoff_coefficient=0.8),
    ]

    rows = _report_surface_rows(config)

    assert [row["name"] for row in rows] == ["Used roof"]


def test_report_charts_mark_selected_tank_with_red_circle() -> None:
    monthly_demand = [
        {
            "month": month,
            "demand_per_day": float(index * 100) + 0.6,
            "demand_per_month": float(index * 3000) + 0.6,
        }
        for index, month in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)
    ]
    report = {
        "metadata": {
            "client_name": "Client",
            "date": "2026-07-15",
            "location": "Location",
            "project_name": "Project",
            "author_name": "Jane Engineer",
            "end_uses": "Demand",
        },
        "area_unit": "sq ft",
        "volume_unit": "gal",
        "precipitation_unit": "in",
        "average_annual_precipitation": 42.375,
        "precipitation_basis": "Rain only",
        "notes": "Coordinate with facilities.\nConfirm irrigation schedule.",
        "surfaces": [],
        "monthly_demand": monthly_demand,
        "total_annual_demand": 365000.6,
        "yearly_reliability": [
            {
                "year": 2024,
                "total_days": 366,
                "met_days": 300,
                "unmet_days": 66,
                "met_percent": 81.967213,
                "unmet_percent": 18.032787,
            },
            {
                "year": 2025,
                "total_days": 365,
                "met_days": 250,
                "unmet_days": 115,
                "met_percent": 68.493151,
                "unmet_percent": 31.506849,
            },
        ],
        "tank_level_distribution": [
            {"low": index * 1000.0, "high": (index + 1) * 1000.0, "count": (index + 1) * 10}
            for index in range(6)
        ],
        "curve": [
            {"tank_size": 500.0, "reliability": 50.0},
            {"tank_size": 1000.0, "reliability": 75.0},
        ],
        "selected_tank_size": 750.0,
        "selected_reliability": 65.0,
        "include_multitank_charts": True,
        "include_system_visualization": True,
        "system_type": "Indirect system",
        "multitank_charts": [
            {
                "title": "Yearly demand reliability - multitank",
                "x_label": "Year",
                "y_label": "Demand met (%)",
                "interactive_series_toggle": True,
                "series": [
                    {"label": "1,000 gal", "points": [(2024.0, 70.0), (2025.0, 72.0)]},
                    {"label": "1,500 gal", "points": [(2024.0, 80.0), (2025.0, 82.0)]},
                ],
            },
            {
                "type": "yearly_stacked",
                "title": "Yearly Demand Reliability - 1,500 gal tank",
                "yearly_reliability": [
                    {
                        "year": 2024,
                        "total_days": 366,
                        "met_days": 320,
                        "unmet_days": 46,
                        "met_percent": 87.431694,
                        "unmet_percent": 12.568306,
                    }
                ],
                "selected_reliability": 87.43,
            },
            {
                "type": "tank_history",
                "title": "Tank Water Over Time (gal)",
                "x_label": "Day of year",
                "y_label": "gal",
                "series": [
                    {
                        "label": "1,000 gal",
                        "points": [(0.0, 100.0), (1.0, 200.0)],
                        "yearly_points": {
                            "2024": [(1.0, 100.0), (2.0, 200.0)],
                            "2025": [(1.0, 150.0), (2.0, 250.0)],
                        },
                        "dated_points": [
                            ("2024-01-01", 100.0), ("2024-02-01", 200.0),
                            ("2025-01-01", 150.0), ("2025-02-01", 250.0),
                        ],
                    },
                    {
                        "label": "1,500 gal",
                        "points": [(0.0, 200.0), (1.0, 300.0)],
                        "yearly_points": {
                            "2024": [(1.0, 200.0), (2.0, 300.0)],
                            "2025": [(1.0, 250.0), (2.0, 350.0)],
                        },
                        "dated_points": [
                            ("2024-01-01", 200.0), ("2024-02-01", 300.0),
                            ("2025-01-01", 250.0), ("2025-02-01", 350.0),
                        ],
                    },
                ],
            },
        ],
    }

    html = RainwaterTkApp._build_report_html(None, report)
    latex = RainwaterTkApp._build_report_latex(None, report)
    pdf_commands: list[str] = []
    RainwaterTkApp._draw_pdf_reliability_curve(None, pdf_commands, 0, 0, 400, 200, report)
    yearly_pdf_commands: list[str] = []
    RainwaterTkApp._draw_pdf_yearly_demand_reliability(None, yearly_pdf_commands, 0, 0, 400, 200, report)
    distribution_pdf_commands: list[str] = []
    RainwaterTkApp._draw_pdf_tank_level_distribution(None, distribution_pdf_commands, 0, 0, 400, 200, report)

    assert '<circle class="selected-tank"' in html
    assert "RWH Calculator Report - multi-tank" in html
    assert ".axis-label { fill:var(--muted); font-size:15px; font-weight:700; }" in html
    assert "stroke:#d71920" in html
    assert "Primary tank size" in html
    assert "<h2>Tank summary</h2>" in html
    assert 'id="system-visualization"' in html
    assert "System visualization - Indirect system" in html
    assert "Filtration pump" in html
    assert "Booster pump" in html
    assert "Municipal water backup" in html
    assert html.index('id="tank-summary"') < html.index('id="system-visualization"') < html.index('id="demand-summary"')
    assert "750 gal" in html
    assert "<h2>Demand summary</h2>" in html
    assert 'aria-label="Table of contents"' in html
    assert 'class="report-shell"' in html
    assert ".toc { position:sticky" in html
    assert "IntersectionObserver" in html
    assert 'id="toc-toggle"' in html
    assert "Hide contents" in html
    assert "toc-collapsed" in html
    assert "rwh-report-toc-collapsed" in html
    assert 'href="#demand-summary"' in html
    assert 'href="#notes"' in html
    assert 'href="#yearly-demand-reliability"' in html
    assert 'href="#tank-level-distribution"' in html
    assert html.index('id="project-information"') < html.index('id="notes"') < html.index('id="surface-area-summary"')
    assert "Coordinate with facilities.\nConfirm irrigation schedule." in html
    assert "<td>101</td><td>3,001</td>" in html
    assert "365,001 gal" in html
    assert "Produced by Jane Engineer" in html
    assert "Selected tank size" in html
    assert "750 gal" in html
    assert "42.38 in" in html
    assert "Rain only" in html
    assert html.index('id="reliability-curve"') < html.index('id="yearly-demand-reliability"')
    assert "Yearly demand reliability - 750 gal tank" in html
    assert "Demand not met" in html
    assert "2024: demand met 300 days (81.97%); demand not met 66 days (18.03%)" in html
    assert "Average tank reliability over 2 years: 65.00%" in html
    assert "Yearly Demand Reliability - 1,500 gal tank" in html
    assert "Average tank reliability over 1 year: 87.43%" in html
    assert 'id="chart-tooltip"' in html
    assert 'data-tooltip="2024 tank reliability: 87.43%"' in html
    assert "document.querySelectorAll('[data-tooltip]')" in html
    assert 'data-tooltip="2024 tank reliability: 87.43%"><title>' not in html
    assert "Yearly demand reliability - multitank" in html
    assert html.count('class="series-toggle"') == 4
    assert "multitank-chart-1-series-1" in html
    assert 'href="#multitank-chart-1"' in html
    assert "multitank-chart-1-series-2" in html
    assert 'class="tank-history"' in html
    assert 'data-years="2024,2025"' in html
    assert html.count("data-history-series-toggle") >= 2
    assert "changeTankHistoryYear" in html
    assert "refreshTankHistory" in html
    assert "setTankHistoryMode" in html
    assert "Custom range" in html
    assert "data-range-start" in html
    assert "data-range-end" in html
    assert 'class="tank-history-point"' in html
    assert 'data-tooltip="1,000 gal; 2024, day 1: 100.00 gal"' in html
    assert ".tank-history-point:hover" in html
    assert html.index('id="yearly-demand-reliability"') < html.index('id="tank-level-distribution"')
    assert "mark=o, red" in latex
    assert r"\title{RWH Calculator Report - multi-tank}" in latex
    assert r"label style={font=\bfseries\normalsize}" in latex
    assert r"\addlegendentry{Primary tank size}" in latex
    assert r"\usepackage[hidelinks]{hyperref}" in latex
    assert r"\tableofcontents" in latex
    assert r"\section{Tank Summary}" in latex
    assert r"\section{System Visualization - Indirect system}" in latex
    assert r"\textbf{Selected tank size} & 750 gal" in latex
    assert r"\section{Notes}" in latex
    assert latex.index(r"\section{Project Information}") < latex.index(r"\section{Notes}") < latex.index(r"\section{Surface Area Summary}")
    assert r"Coordinate with facilities.\par Confirm irrigation schedule." in latex
    assert "750 gal" in latex
    assert r"\section{Demand Summary}" in latex
    assert "365,001 gal" in latex
    assert r"\textbf{Produced by:} Jane Engineer" in latex
    assert "42.375 in" in latex
    assert "Rain only" in latex
    assert r"\section{Yearly Demand Reliability - 750 gal tank}" in latex
    assert r"\section{Yearly Demand Reliability - 1,500 gal tank}" in latex
    assert "ybar stacked" in latex
    assert latex.index(r"\section{Reliability Curve}") < latex.index(
        r"\section{Yearly Demand Reliability - 750 gal tank}"
    )
    assert r"\section{Tank Level Distribution}" in latex
    assert latex.index(r"\section{Yearly Demand Reliability - 750 gal tank}") < latex.index(
        r"\section{Tank Level Distribution}"
    )
    assert any("0.84 0.05 0.08 RG" in command and command.endswith(" c S") for command in pdf_commands)
    assert any("Primary tank size" in command for command in pdf_commands)
    assert any("/F2 9 Tf" in command and "Tank size" in command for command in pdf_commands)
    assert any("/F2 9 Tf 0 1 -1 0" in command and "Reliability %" in command for command in pdf_commands)
    assert any("0.18 0.55 0.34 rg" in command for command in yearly_pdf_commands)
    assert any("0.79 0.30 0.30 rg" in command for command in yearly_pdf_commands)
    assert any("0.18 0.55 0.34 rg" in command for command in distribution_pdf_commands)
    assert any("5,000-6,000" in command for command in distribution_pdf_commands)

    report["metadata"]["author_name"] = ""
    assert "Produced by" not in RainwaterTkApp._build_report_html(None, report)
    assert "Produced by" not in RainwaterTkApp._build_report_latex(None, report)


def test_report_demand_summary_uses_simulated_monthly_and_annual_demand() -> None:
    config = default_project_config()
    results = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-02-01", "2026-01-01"]),
            "DemandGallons": [100.0, 200.0, 300.0, 400.0],
        }
    )

    monthly, annual = _report_demand_summary(results, config)

    assert monthly[0] == {
        "month": "Jan",
        "demand_per_day": 700.0 / 3.0,
        "demand_per_month": 350.0,
    }
    assert monthly[1] == {"month": "Feb", "demand_per_day": 300.0, "demand_per_month": 300.0}
    assert monthly[2] == {"month": "Mar", "demand_per_day": 0.0, "demand_per_month": 0.0}
    assert annual == 500.0


def test_pypdf_report_contents_links_and_outlines_are_navigable(tmp_path) -> None:
    output = tmp_path / "report.pdf"
    pages = [
        ["BT /F1 10 Tf 1 0 0 1 54 700 Tm (Table of Contents) Tj ET"],
        ["BT /F1 10 Tf 1 0 0 1 54 700 Tm (Project Information) Tj ET"],
    ]

    RainwaterTkApp._write_pdf_with_pypdf(
        None,
        output,
        pages,
        {"Project Information": 1},
        [((54.0, 680.0, 250.0, 710.0), "Project Information")],
    )

    reader = PdfReader(output)
    assert reader.outline[0].title == "Project Information"
    assert len(reader.pages[0]["/Annots"]) == 1


def test_yearly_demand_reliability_bars_sum_to_100_percent() -> None:
    dates = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    results = pd.DataFrame(
        {
            "Date": dates,
            "DemandMet": [index % 2 == 0 for index in range(len(dates))],
        }
    )

    yearly = _yearly_demand_reliability(results)

    assert [row["total_days"] for row in yearly] == [366, 365]
    assert all(row["met_days"] + row["unmet_days"] == row["total_days"] for row in yearly)
    assert all(row["met_percent"] + row["unmet_percent"] == 100.0 for row in yearly)


def test_report_average_annual_precipitation_uses_project_units() -> None:
    rainfall = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-01", "2024-02-01", "2025-01-01"]),
            "Precipitation": [1.0, 2.0, 4.0],
        }
    )
    imperial = default_project_config()
    metric = default_project_config()
    metric.unit_system = "Metric"

    assert _report_average_annual_precipitation(rainfall, imperial) == 3.5
    assert _report_average_annual_precipitation(rainfall, metric) == pytest.approx(88.9)


def test_report_tank_level_distribution_uses_six_bins_and_all_days() -> None:
    config = default_project_config()
    config.selected_tank_size_gal = 600.0
    results = pd.DataFrame({"WaterInTankGallons": [0.0, 50.0, 100.0, 250.0, 599.0, 600.0]})

    distribution = _report_tank_level_distribution(results, config)

    assert len(distribution) == 6
    assert sum(int(row["count"]) for row in distribution) == len(results)
    assert distribution[0] == {"low": 0.0, "high": 100.0, "count": 2}
    assert distribution[-1] == {"low": 500.0, "high": 600.0, "count": 2}


def test_reverse_system_connection_routes_around_object_bodies() -> None:
    points = RainwaterTkApp._system_connection_points(500.0, 180.0, 220.0, 180.0, 420.0)

    coordinate_pairs = list(zip(points[::2], points[1::2]))
    assert len(coordinate_pairs) == 6
    assert coordinate_pairs[0] == (568.0, 180.0)
    assert coordinate_pairs[-1] == (152.0, 180.0)
    assert any(y < 150.0 for _x, y in coordinate_pairs)
    assert coordinate_pairs[-2][0] < 158.0


def test_forward_system_connection_uses_compact_orthogonal_route() -> None:
    points = RainwaterTkApp._system_connection_points(100.0, 100.0, 400.0, 220.0, 420.0)

    assert len(points) == 8
    assert points[:2] == (168.0, 100.0)
    assert points[-2:] == (332.0, 220.0)


def test_reverse_connection_uses_gap_when_source_is_above_target() -> None:
    points = RainwaterTkApp._system_connection_points(500.0, 100.0, 220.0, 260.0, 420.0)
    coordinate_pairs = list(zip(points[::2], points[1::2]))

    assert coordinate_pairs == [
        (568.0, 100.0),
        (592.0, 100.0),
        (592.0, 180.0),
        (128.0, 180.0),
        (128.0, 260.0),
        (152.0, 260.0),
    ]


def test_system_block_collision_includes_visual_spacing() -> None:
    assert RainwaterTkApp._system_blocks_overlap(100.0, 100.0, 220.0, 100.0)
    assert RainwaterTkApp._system_blocks_overlap(100.0, 100.0, 100.0, 160.0)
    assert not RainwaterTkApp._system_blocks_overlap(100.0, 100.0, 232.0, 100.0)
    assert not RainwaterTkApp._system_blocks_overlap(100.0, 100.0, 100.0, 168.0)


def test_node_disconnect_only_removes_connections_for_selected_direction() -> None:
    connections = [
        {"source_component": "a", "target_component": "b"},
        {"source_component": "b", "target_component": "c"},
        {"source_component": "d", "target_component": "b"},
    ]

    assert RainwaterTkApp._connections_after_node_disconnect(connections, "b", "in") == [
        {"source_component": "b", "target_component": "c"}
    ]
    assert RainwaterTkApp._connections_after_node_disconnect(connections, "b", "out") == [
        {"source_component": "a", "target_component": "b"},
        {"source_component": "d", "target_component": "b"},
    ]
    assert RainwaterTkApp._connections_after_node_disconnect(connections, "b", None) == []
