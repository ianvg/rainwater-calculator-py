import pandas as pd

from rainwater_app.analysis_state import analysis_input_signature
from rainwater_app.defaults import default_project_config


def _rainfall() -> pd.DataFrame:
    return pd.DataFrame(
        {"Date": pd.date_range("2025-01-01", periods=3), "Precipitation": [0.1, 0.0, 0.2]}
    )


def test_signature_changes_when_calculation_input_changes() -> None:
    config = default_project_config()
    before = analysis_input_signature(config, _rainfall())

    config.surfaces[0].area += 1.0

    assert analysis_input_signature(config, _rainfall()) != before


def test_signature_changes_when_rainfall_changes() -> None:
    config = default_project_config()
    rainfall = _rainfall()
    before = analysis_input_signature(config, rainfall)

    rainfall.loc[1, "Precipitation"] = 0.5

    assert analysis_input_signature(config, rainfall) != before


def test_signature_changes_when_comparison_tank_sizes_change() -> None:
    config = default_project_config()
    before = analysis_input_signature(config, _rainfall())

    config.comparison_tank_sizes_gal = [2500.0, 7500.0]

    assert analysis_input_signature(config, _rainfall()) != before


def test_signature_changes_when_custom_system_topology_changes() -> None:
    config = default_project_config()
    before = analysis_input_signature(config, _rainfall())

    config.system_type = "Custom system"
    config.system_connections.append({"source_component": "source", "target_component": "tank"})

    assert analysis_input_signature(config, _rainfall()) != before


def test_signature_ignores_project_metadata_and_rainfall_row_order() -> None:
    config = default_project_config()
    rainfall = _rainfall()
    before = analysis_input_signature(config, rainfall)

    config.name = "Renamed project"
    config.street_address = "123 Example Street"
    config.latitude = 40.0
    config.longitude = -75.0
    config.unit_system = "Metric"

    assert analysis_input_signature(config, rainfall.iloc[::-1]) == before
