from rainwater_app.defaults import default_project_config
from rainwater_app.models import Surface
from tkinter_app import RainwaterTkApp, _report_surface_rows


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
