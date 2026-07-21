from __future__ import annotations

import copy

import pandas as pd

from rainwater_app.defaults import default_project_config
from rainwater_app.project_state import WorkingDraftStore, project_state_fingerprint


def test_project_state_fingerprint_tracks_model_data_and_pending_form_values() -> None:
    config = default_project_config()
    rainfall = pd.DataFrame(
        {"Date": pd.to_datetime(["2025-01-01"]), "Precipitation": [1.25]}
    )
    baseline = project_state_fingerprint(
        config,
        rainfall,
        form_values={"project_name_var": config.name},
        notes="Initial note",
    )

    assert baseline == project_state_fingerprint(
        copy.deepcopy(config),
        rainfall.copy(),
        form_values={"project_name_var": config.name},
        notes="Initial note",
    )

    changed_config = copy.deepcopy(config)
    changed_config.author_name = "A different author"
    assert baseline != project_state_fingerprint(
        changed_config,
        rainfall,
        form_values={"project_name_var": config.name},
        notes="Initial note",
    )
    assert baseline != project_state_fingerprint(
        config,
        rainfall.assign(Precipitation=[2.5]),
        form_values={"project_name_var": config.name},
        notes="Initial note",
    )
    assert baseline != project_state_fingerprint(
        config,
        rainfall,
        form_values={"project_name_var": "Pending name"},
        notes="Initial note",
    )
    assert baseline != project_state_fingerprint(
        config,
        rainfall,
        form_values={"project_name_var": config.name},
        notes="Edited note",
    )


def test_working_draft_round_trip_and_clear(tmp_path) -> None:
    config = default_project_config()
    config.name = "Recovered design"
    rainfall = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
            "Precipitation": [1.25, 0.0],
        }
    )
    curve = pd.DataFrame({"TankSizeGallons": [1000.0], "ReliabilityPercent": [82.0]})
    results = pd.DataFrame({"ReliabilityPercent": [82.0], "OverflowGallons": [10.0]})
    comparison = pd.DataFrame(
        {"ComparisonTankSizeGallons": [1000.0], "ReliabilityPercent": [82.0]}
    )
    hourly = pd.DataFrame({"DateTime": pd.to_datetime(["2025-01-01 00:00"]), "Tank": [5.0]})
    draft_store = WorkingDraftStore(tmp_path / "recovery")

    draft_store.save(
        config,
        rainfall,
        curve,
        results,
        comparison,
        hourly,
        project_file_path=tmp_path / "projects.db",
        baseline_fingerprint="saved-state",
        form_values={"project_name_var": "Pending recovered name", "unit_var": "Metric"},
        notes="Unsaved notes",
    )

    assert draft_store.exists()
    recovered = draft_store.load()
    assert recovered.config.name == "Recovered design"
    assert recovered.metadata.project_file_path == str(tmp_path / "projects.db")
    assert recovered.metadata.baseline_fingerprint == "saved-state"
    assert recovered.metadata.form_values["project_name_var"] == "Pending recovered name"
    assert recovered.metadata.notes == "Unsaved notes"
    pd.testing.assert_frame_equal(recovered.rainfall_df, rainfall)
    pd.testing.assert_frame_equal(recovered.curve_df, curve, check_dtype=False)
    pd.testing.assert_frame_equal(recovered.results_df, results, check_dtype=False)
    pd.testing.assert_frame_equal(
        recovered.comparison_results_df, comparison, check_dtype=False
    )
    pd.testing.assert_frame_equal(recovered.hourly_results_df, hourly, check_dtype=False)

    draft_store.clear()
    assert not draft_store.exists()
    assert not list(draft_store.backup_dir.glob("working_draft-*.db"))
