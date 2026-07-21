from __future__ import annotations

import pandas as pd
import pytest

from rainwater_app.analysis_service import AnalysisProgressEvent, AnalysisService
from rainwater_app.defaults import default_project_config
from rainwater_app.engine import AnalysisCancelledError
from rainwater_app.models import Surface


def test_analysis_service_runs_selected_curve_hourly_and_comparison_paths() -> None:
    config = default_project_config("Service analysis")
    config.surfaces = [Surface("Roof", 1_000.0, 0.9)]
    config.demand.simple_daily_demand_gallons = 10.0
    config.demand.hourly_schedule_enabled = True
    config.graph_start_gal = 100
    config.graph_end_gal = 200
    config.graph_step_gal = 100
    config.selected_tank_size_gal = 100.0
    config.comparison_tank_sizes_gal = [100.0, 200.0]
    rainfall = pd.DataFrame(
        {"Date": pd.date_range("2025-01-01", periods=2), "Precipitation": [1.0, 0.0]}
    )
    events: list[AnalysisProgressEvent] = []

    outcome = AnalysisService().run(
        config,
        rainfall,
        include_comparisons=True,
        progress_callback=events.append,
    )

    assert len(outcome.curve) == 2
    assert not outcome.selected_tank.empty
    assert not outcome.hourly_selected_tank.empty
    assert set(outcome.comparison_tanks) == {100.0, 200.0}
    assert {event.phase for event in events} == {
        "reliability_curve", "selected_tank", "comparison_tank"
    }


def test_analysis_service_honors_cancellation_without_ui_state() -> None:
    config = default_project_config("Cancelled")
    config.graph_start_gal = 100
    config.graph_end_gal = 200
    config.graph_step_gal = 100
    config.selected_tank_size_gal = 100.0
    rainfall = pd.DataFrame(
        {"Date": pd.date_range("2025-01-01", periods=2), "Precipitation": [0.0, 0.0]}
    )

    with pytest.raises(AnalysisCancelledError):
        AnalysisService().run(config, rainfall, cancel_callback=lambda: True)
