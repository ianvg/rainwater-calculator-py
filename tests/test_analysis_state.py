import pandas as pd

from rainwater_app.analysis_state import analysis_input_signature
from rainwater_app.defaults import default_project_config
from rainwater_app.rainfall import disaggregate_daily_rainfall_hyetos


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


def test_signature_changes_when_hourly_rainfall_profile_changes() -> None:
    config = default_project_config()
    first = disaggregate_daily_rainfall_hyetos(_rainfall(), seed=1)
    second = disaggregate_daily_rainfall_hyetos(_rainfall(), seed=2)

    assert analysis_input_signature(config, first) != analysis_input_signature(config, second)


def test_signature_changes_when_synthetic_hourly_use_changes() -> None:
    config = default_project_config()
    before = analysis_input_signature(config, _rainfall())

    config.use_synthetic_hourly_rainfall = True

    assert analysis_input_signature(config, _rainfall()) != before


def test_signature_changes_when_comparison_tank_sizes_change() -> None:
    config = default_project_config()
    before = analysis_input_signature(config, _rainfall())

    config.comparison_tank_sizes_gal = [2500.0, 7500.0]

    assert analysis_input_signature(config, _rainfall()) != before


def test_signature_changes_when_system_layout_changes() -> None:
    config = default_project_config()
    before = analysis_input_signature(config, _rainfall())

    config.system_layout.append({"id": "tank", "component_type": "primary_tank"})

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


def test_signature_ignores_presentation_only_recommendation_assumptions() -> None:
    config = default_project_config()
    before = analysis_input_signature(config, _rainfall())

    config.recommendation_reliability_target_percent = 95.0
    config.recommendation_marginal_gain_threshold = 0.5

    assert analysis_input_signature(config, _rainfall()) == before
