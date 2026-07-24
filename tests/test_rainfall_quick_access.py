from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

import tkinter_app
from rainwater_app.defaults import default_project_config
from rainwater_app.models import METRIC_UNIT_SYSTEM
from tkinter_app import RainwaterTkApp


class _VariableStub:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


def test_preference_path_list_deduplicates_case_insensitively_and_limits(tmp_path) -> None:
    first = tmp_path / "First.csv"
    second = tmp_path / "Second.csv"
    app = SimpleNamespace(
        app_preferences={
            "paths": [str(first), str(first).upper(), "", None, str(second)]
        }
    )

    paths = RainwaterTkApp._preference_path_list(app, "paths", 2)

    assert paths == [str(first.resolve()), str(second.resolve())]


def test_remember_recent_rainfall_csv_moves_existing_file_to_front(tmp_path) -> None:
    first = str((tmp_path / "first.csv").resolve())
    second = str((tmp_path / "second.csv").resolve())
    calls: list[str] = []
    app = SimpleNamespace(
        recent_rainfall_csv_paths=[first, second],
        _save_app_preferences=lambda: calls.append("save"),
        _refresh_rainfall_quick_access_menu=lambda: calls.append("refresh"),
    )

    RainwaterTkApp._remember_recent_rainfall_csv(app, tmp_path / "second.csv")

    assert app.recent_rainfall_csv_paths == [second, first]
    assert calls == ["save", "refresh"]


def test_save_rainfall_csv_exports_reloadable_daily_values_in_project_units(
    tmp_path, monkeypatch
) -> None:
    destination = tmp_path / "saved.csv"
    config = default_project_config("Export test")
    config.unit_system = METRIC_UNIT_SYSTEM
    status = _VariableStub()
    app = SimpleNamespace(
        rainfall_df=pd.DataFrame(
            {
                "Date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
                "Precipitation": [1.0, 0.5],
                "HourlyPrecipitation00": [0.2, 0.1],
            }
        ),
        config_model=config,
        current_rainfall_csv_path=None,
        rainfall_source_label=None,
        status_var=status,
        execution_log=SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
        ),
        _apply_form_to_model=lambda: None,
    )
    app._default_rainfall_csv_filename = lambda: (
        RainwaterTkApp._default_rainfall_csv_filename(app)
    )
    monkeypatch.setattr(
        tkinter_app.filedialog, "asksaveasfilename", lambda **_kwargs: str(destination)
    )

    RainwaterTkApp.save_rainfall_csv(app)

    exported = pd.read_csv(destination)
    assert list(exported.columns) == ["Date", "Precipitation"]
    assert exported["Date"].tolist() == ["2025-01-01", "2025-01-02"]
    assert exported["Precipitation"].tolist() == [25.4, 12.7]
    assert "mm" in status.value


def test_default_rainfall_csv_filename_uses_imported_station_name() -> None:
    config = default_project_config("Export test")
    app = SimpleNamespace(
        rainfall_source_label=(
            "CENTRAL/PARK (123456) in New York via ACIS, Total precipitation"
        ),
        config_model=config,
        current_rainfall_csv_path=None,
    )

    filename = RainwaterTkApp._default_rainfall_csv_filename(app)

    assert filename == "CENTRAL_PARK.csv"
