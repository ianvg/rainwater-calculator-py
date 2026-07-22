import pandas as pd
import pytest
from pypdf import PdfReader

from rainwater_app.climate_normals import PRECIPITATION_NORMAL_RECORD_KEYS
from rainwater_app.defaults import default_project_config
from rainwater_app.models import (
    DemandObject,
    METRIC_UNIT_SYSTEM,
    Surface,
    WEEKDAY_KEYS,
    purge_unused_hourly_schedules,
    unused_hourly_schedule_names,
)
from rainwater_app.reporting import (
    ReportModel,
    report_average_annual_precipitation as _report_average_annual_precipitation,
    report_demand_summary as _report_demand_summary,
    report_surface_rows as _report_surface_rows,
    report_tank_level_distribution as _report_tank_level_distribution,
    tank_volume_capacity_label as _tank_volume_capacity_label,
    yearly_demand_reliability as _yearly_demand_reliability,
)
from rainwater_app.ui_logic import (
    antecedent_dry_period_from_days as _antecedent_dry_period_from_days,
    antecedent_dry_period_to_days as _antecedent_dry_period_to_days,
    demand_flow_from_gallons_per_minute as _demand_flow_from_gallons_per_minute,
    demand_flow_to_gallons_per_minute as _demand_flow_to_gallons_per_minute,
    graph_step_count as _graph_step_count,
    normalized_demand_object_indices as _normalized_demand_object_indices,
    parse_coordinates as _parse_coordinates,
    system_object_editor_validation as _system_object_editor_validation,
    validated_demand_object_library as _validated_demand_object_library,
    validated_schedule_library as _validated_schedule_library,
)
from tkinter_app import RainwaterTkApp, _normalize_text_scale_percent
from tkinter_app import DemandObjectDialog


class _VariableStub:
    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 100), (True, 100), ("invalid", 100), (80, 80), ("110", 110), (119, 125), (999, 150)],
)
def test_text_scale_preference_uses_the_closest_supported_percentage(value, expected) -> None:
    assert _normalize_text_scale_percent(value) == expected


class _WidgetStateStub:
    def __init__(self) -> None:
        self.last_state = None

    def state(self, state) -> None:
        self.last_state = state


class _AnalysisCanvasStub:
    def __init__(self) -> None:
        self.scroll_calls = []
        self.item_configuration = None
        self.configuration = None

    def winfo_rootx(self) -> int:
        return 10

    def winfo_rooty(self) -> int:
        return 20

    def winfo_width(self) -> int:
        return 500

    def winfo_height(self) -> int:
        return 400

    def yview_scroll(self, direction, unit) -> None:
        self.scroll_calls.append((direction, unit))

    def itemconfigure(self, window, **configuration) -> None:
        self.item_configuration = (window, configuration)

    def bbox(self, _tag):
        return (0, 0, 500, 900)

    def configure(self, **configuration) -> None:
        self.configuration = configuration


def test_analysis_scroll_helpers_resize_track_and_scroll_visible_content() -> None:
    app = object.__new__(RainwaterTkApp)
    app.analysis_tab = "analysis-tab"
    app.notebook = type("Notebook", (), {"select": lambda self: "analysis-tab"})()
    app.analysis_scroll_canvas = _AnalysisCanvasStub()
    app.analysis_scroll_window = "content-window"
    app.winfo_pointerxy = lambda: (100, 100)
    resize_event = type("ResizeEvent", (), {"width": 720})()
    wheel_event = type("WheelEvent", (), {"num": None, "delta": -120})()

    app._resize_analysis_scroll_content(resize_event)
    app._update_analysis_scroll_region()
    handled = app._scroll_analysis_mousewheel(wheel_event)

    assert app.analysis_scroll_canvas.item_configuration == (
        "content-window",
        {"width": 720},
    )
    assert app.analysis_scroll_canvas.configuration == {
        "scrollregion": (0, 0, 500, 900)
    }
    assert app.analysis_scroll_canvas.scroll_calls == [(1, "units")]
    assert handled == "break"


def test_occupational_modes_only_list_binary_occupancy_schedules() -> None:
    dialog = object.__new__(DemandObjectDialog)
    dialog.project_schedule_names = ["Fractional", "Occupied"]
    dialog.config_model = default_project_config()
    dialog.config_model.demand.hourly_schedule_library = {
        "Fractional": {},
        "Occupied": {},
    }
    dialog.config_model.demand.hourly_schedule_types = {
        "Fractional": "fractional",
        "Occupied": "occupancy",
    }

    for mode in ("fixture_usage", "recurring_daily", "monthly_volume"):
        assert dialog._compatible_schedule_names(mode) == ["Occupied"]
    assert dialog._compatible_schedule_names("scheduled_flow") == [
        "Fractional",
        "Occupied",
    ]


def test_occupational_demand_modes_have_clear_visible_prefix() -> None:
    assert DemandObjectDialog.MODE_LABELS[
        "Occupational - Fixture use (people x uses)"
    ] == "fixture_usage"
    assert DemandObjectDialog.MODE_LABELS[
        "Occupational - Recurring daily volume"
    ] == "recurring_daily"
    assert DemandObjectDialog.MODE_LABELS[
        "Occupational - Monthly volume"
    ] == "monthly_volume"


def test_custom_schedule_library_preserves_schedule_types(tmp_path) -> None:
    schedule = {
        day: [1.0] * 24
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    path = tmp_path / "schedule_library.json"
    app = object.__new__(RainwaterTkApp)
    app.custom_schedule_library_path = path
    app.custom_schedule_templates = {"Office occupied": schedule}
    app.custom_schedule_template_types = {"Office occupied": "occupancy"}

    app._save_custom_schedule_templates()

    loaded_app = object.__new__(RainwaterTkApp)
    loaded_app.custom_schedule_library_path = path
    loaded_app.custom_schedule_template_types = {}
    loaded = loaded_app._load_custom_schedule_templates()
    assert loaded == {"Office occupied": schedule}
    assert loaded_app.custom_schedule_template_types == {
        "Office occupied": "occupancy"
    }


def _analysis_settings_app(*, hourly: bool, synthetic: bool, generated: bool):
    app = object.__new__(RainwaterTkApp)
    app.config_model = default_project_config()
    app.config_model.demand.active_hourly_schedule_name = "Office week"
    app.hourly_schedule_enabled_var = _VariableStub(hourly)
    app.use_synthetic_hourly_rainfall_var = _VariableStub(synthetic)
    app.applied_analysis_resolution_var = _VariableStub()
    app.applied_rainfall_source_var = _VariableStub()
    app.applied_demand_timing_var = _VariableStub()
    app.applied_rainfall_timing_var = _VariableStub()
    app.hourly_schedule_change_button = _WidgetStateStub()
    app.daily_rainfall_timing_radio = _WidgetStateStub()
    app.synthetic_hourly_rainfall_radio = _WidgetStateStub()
    app.analysis_generate_hourly_rainfall_button = _WidgetStateStub()
    app.rainfall_df = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [1.0]})
    if generated:
        for hour in range(24):
            app.rainfall_df[f"HourlyPrecipitation{hour:02d}"] = 1.0 / 24.0
    return app


def test_applied_analysis_settings_describe_daily_only_mode() -> None:
    app = _analysis_settings_app(hourly=False, synthetic=True, generated=True)

    app._refresh_applied_analysis_settings()

    assert app.applied_analysis_resolution_var.get() == "Daily only"
    assert app.applied_rainfall_source_var.get() == "Loaded daily rainfall record"
    assert app.applied_demand_timing_var.get() == "Daily totals (hourly simulation is off)"
    assert app.applied_rainfall_timing_var.get() == "Daily totals"
    assert app.synthetic_hourly_rainfall_radio.last_state == ["disabled"]
    assert app.analysis_generate_hourly_rainfall_button.last_state == ["disabled"]


@pytest.mark.parametrize(
    ("synthetic", "generated", "expected_rainfall_timing"),
    [
        (False, False, "Each daily rainfall total is applied at 23:00"),
        (True, True, "Synthetic hourly profile derived from each daily rainfall total"),
        (
            True,
            False,
            "Synthetic hourly timing selected, but no profile has been generated",
        ),
    ],
)
def test_applied_analysis_settings_describe_hourly_timing(
    synthetic: bool, generated: bool, expected_rainfall_timing: str
) -> None:
    app = _analysis_settings_app(
        hourly=True, synthetic=synthetic, generated=generated
    )

    app._refresh_applied_analysis_settings()

    assert app.applied_analysis_resolution_var.get() == (
        "Daily + hourly (the daily analysis is always included)"
    )
    assert app.applied_demand_timing_var.get() == (
        "Hourly schedules (project default: Office week)"
    )
    assert app.applied_rainfall_timing_var.get() == expected_rainfall_timing
    assert app.synthetic_hourly_rainfall_radio.last_state == (
        ["!disabled"] if generated else ["disabled"]
    )
    assert app.analysis_generate_hourly_rainfall_button.last_state == ["!disabled"]


def test_antecedent_dry_period_converts_between_days_and_hours() -> None:
    assert _antecedent_dry_period_from_days(1.5, "hours") == 36.0
    assert _antecedent_dry_period_to_days(36.0, "hours") == 1.5
    assert _antecedent_dry_period_from_days(1.5, "days") == 1.5


def test_purge_unused_schedules_preserves_active_and_assigned_objects() -> None:
    demand = default_project_config().demand
    profile = {day: [1.0] * 24 for day in WEEKDAY_KEYS}
    demand.hourly_schedule_library = {
        "Active": profile,
        "Assigned": profile,
        "Unused morning": profile,
        "Unused evening": profile,
    }
    demand.active_hourly_schedule_name = "Active"
    demand.demand_objects = [
        DemandObject("Irrigation", schedule_name="Assigned"),
    ]

    assert unused_hourly_schedule_names(demand) == [
        "Unused morning",
        "Unused evening",
    ]
    assert purge_unused_hourly_schedules(demand) == [
        "Unused morning",
        "Unused evening",
    ]
    assert list(demand.hourly_schedule_library) == ["Active", "Assigned"]


def _valid_primary_editor_values() -> dict[str, object]:
    return {
        "name": "Primary tank",
        "selected_tank_size": "5,000",
        "initial_fill": "50",
        "reserve": "10",
        "graph_start": "500",
        "graph_end": "20000",
        "graph_step": "500",
        "graph_auto_step_count": "39",
    }


def test_system_object_editor_accepts_valid_primary_parameters() -> None:
    assert _system_object_editor_validation("primary_tank", _valid_primary_editor_values()) == []


@pytest.mark.parametrize(
    ("start", "end", "step", "expected"),
    [
        (500.0, 20_000.0, 500.0, 39),
        (500.0, 20_000.0, 700.0, 28),
        (0.0, 1_000.0, 2_000.0, 1),
        (500.0, 500.0, 100.0, None),
        (500.0, 20_000.0, 0.0, None),
    ],
)
def test_graph_step_count_tracks_manual_step_size(
    start: float, end: float, step: float, expected: int | None
) -> None:
    assert _graph_step_count(start, end, step) == expected


def test_graph_step_editor_syncs_manual_count_without_overriding_auto_count() -> None:
    class Variable:
        def __init__(self, value: str, on_set=None) -> None:
            self.value = value
            self.on_set = on_set

        def get(self) -> str:
            return self.value

        def set(self, value: str) -> None:
            self.value = value
            if self.on_set is not None:
                self.on_set()

    app = object.__new__(RainwaterTkApp)
    app.system_component_editor_loading = False
    app.system_component_graph_step_autosizing = False
    app.system_component_editor_loaded_id = "primary"
    app.system_builder_selected_id = "primary"
    variables = {
        "graph_start": Variable("500"),
        "graph_end": Variable("20000"),
        "graph_step": Variable("500"),
        "graph_auto_step_count": Variable("39"),
    }
    app.system_component_parameter_vars = variables
    app._system_layout_item = lambda _component_id: {"component_type": "primary_tank"}
    app._system_component_editor_snapshot = lambda _item: {
        key: variable.get() for key, variable in variables.items()
    }
    variables["graph_step"].on_set = app._system_component_graph_step_changed

    variables["graph_step"].set("700")

    assert variables["graph_auto_step_count"].get() == "28"

    variables["graph_start"].set("0")
    variables["graph_end"].set("1000")
    variables["graph_auto_step_count"].set("3")
    app._auto_set_system_component_graph_step()

    assert variables["graph_step"].get() == "333"
    assert variables["graph_auto_step_count"].get() == "3"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", " ", "Name cannot be blank."),
        ("selected_tank_size", "large", "Primary tank size must be a valid number."),
        ("initial_fill", "101", "Initial fill must be between 0 and 100%."),
        ("graph_end", "400", "Graph end tank size must be greater than graph start tank size."),
        ("graph_step", "30000", "Graph step cannot exceed the graph range."),
        ("graph_auto_step_count", "2.5", "Number of steps must be a whole number from 1 to 1000."),
    ],
)
def test_system_object_editor_rejects_invalid_primary_parameters(
    field: str, value: str, message: str
) -> None:
    values = _valid_primary_editor_values()
    values[field] = value

    assert message in _system_object_editor_validation("primary_tank", values)


def test_system_object_editor_validates_other_visible_parameter_types() -> None:
    assert _system_object_editor_validation(
        "filtration_pump", {"name": "Pump", "filtration_pump_capacity": "-1"}
    ) == ["Pump capacity cannot be negative."]
    assert _system_object_editor_validation(
        "filtration_system", {"name": "Filter", "filter_recovery": "101"}
    ) == ["Filter recovery must be between 0 and 100%."]


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


def test_climate_normal_station_label_includes_station_id() -> None:
    label = RainwaterTkApp._climate_normal_station_label(
        {
            "name": "CEDARVILLE, CA US",
            "station_id": "USC00041614",
            "annual_precipitation_inches": 13.12,
            "distance_km": 10.0,
        }
    )

    assert label == "CEDARVILLE, CA US [USC00041614]"


def test_climate_normal_comparison_ranks_wetter_sites_first() -> None:
    app = object.__new__(RainwaterTkApp)
    app.climate_normal_comparison_rows = {
        "dry": {"name": "Dry", "annual_precipitation_inches": 8.0},
        "wet": {"name": "Wet", "annual_precipitation_inches": 42.5},
    }

    assert [row["name"] for row in app._ranked_climate_normal_rows()] == ["Wet", "Dry"]


def test_climate_normal_comparison_sorts_season_column_both_directions() -> None:
    class Tree:
        headings: dict[str, str] = {}

        def heading(self, column: str, *, text: str) -> None:
            self.headings[column] = text

        @staticmethod
        def get_children() -> tuple[()]:
            return ()

        @staticmethod
        def delete(*_items) -> None:
            pass

        @staticmethod
        def insert(*_args, **_kwargs) -> None:
            pass

    app = object.__new__(RainwaterTkApp)
    app.config_model = default_project_config()
    app.climate_normal_comparison_rows = {
        "a": {
            "station_id": "a",
            "name": "Annual wetter",
            "annual_precipitation_inches": 50.0,
            "winter_precipitation_inches": 8.0,
            "spring_precipitation_inches": 12.0,
            "summer_precipitation_inches": 20.0,
            "autumn_precipitation_inches": 10.0,
        },
        "b": {
            "station_id": "b",
            "name": "Winter wetter",
            "annual_precipitation_inches": 40.0,
            "winter_precipitation_inches": 15.0,
            "spring_precipitation_inches": 10.0,
            "summer_precipitation_inches": 8.0,
            "autumn_precipitation_inches": 7.0,
        },
    }
    app.climate_normal_tree = Tree()

    app._sort_climate_normal_comparison("winter")

    assert [row["station_id"] for row in app._ranked_climate_normal_rows()] == ["b", "a"]
    assert app.climate_normal_tree.headings["winter"] == "Winter ▼"

    app._sort_climate_normal_comparison("winter")

    assert [row["station_id"] for row in app._ranked_climate_normal_rows()] == ["a", "b"]
    assert app.climate_normal_tree.headings["winter"] == "Winter ▲"


def test_climate_normal_comparison_sorts_station_names_both_directions() -> None:
    class Tree:
        headings: dict[str, str] = {}

        def heading(self, column: str, *, text: str) -> None:
            self.headings[column] = text

        @staticmethod
        def get_children() -> tuple[()]:
            return ()

        @staticmethod
        def delete(*_items) -> None:
            pass

        @staticmethod
        def insert(*_args, **_kwargs) -> None:
            pass

    app = object.__new__(RainwaterTkApp)
    app.config_model = default_project_config()
    app.climate_normal_comparison_rows = {
        "z": {
            "station_id": "z",
            "name": "Zanesville",
            **{key: 10.0 for key in PRECIPITATION_NORMAL_RECORD_KEYS},
        },
        "a": {
            "station_id": "a",
            "name": "athens",
            **{key: 20.0 for key in PRECIPITATION_NORMAL_RECORD_KEYS},
        },
    }
    app.climate_normal_tree = Tree()

    app._sort_climate_normal_comparison("station")

    assert [row["station_id"] for row in app._ranked_climate_normal_rows()] == ["a", "z"]
    assert app.climate_normal_tree.headings["station"] == "Station ▲"

    app._sort_climate_normal_comparison("station")

    assert [row["station_id"] for row in app._ranked_climate_normal_rows()] == ["z", "a"]
    assert app.climate_normal_tree.headings["station"] == "Station ▼"


def test_climate_normal_comparison_displays_seasons_in_project_units() -> None:
    class Tree:
        inserted: list[tuple[str, tuple[str, ...]]] = []

        @staticmethod
        def get_children() -> tuple[()]:
            return ()

        @staticmethod
        def delete(*_items) -> None:
            pass

        def insert(self, _parent, _position, *, iid: str, values: tuple[str, ...]) -> None:
            self.inserted.append((iid, values))

    class Frame:
        text = ""

        def configure(self, *, text: str) -> None:
            self.text = text

    app = object.__new__(RainwaterTkApp)
    app.config_model = default_project_config()
    app.config_model.unit_system = METRIC_UNIT_SYSTEM
    app.climate_normal_comparison_rows = {
        "USW00013873": {
            "station_id": "USW00013873",
            "name": "ATHENS BEN EPPS AP",
            "annual_precipitation_inches": 1.0,
            "winter_precipitation_inches": 2.0,
            "spring_precipitation_inches": 3.0,
            "summer_precipitation_inches": 4.0,
            "autumn_precipitation_inches": 5.0,
        }
    }
    app.climate_normal_tree = Tree()
    app.climate_normal_comparison_frame = Frame()

    app._refresh_climate_normal_comparison()

    assert app.climate_normal_comparison_frame.text == "Precipitation normals (mm)"
    assert app.climate_normal_tree.inserted == [
        (
            "USW00013873",
            (
                "ATHENS BEN EPPS AP [USW00013873]",
                "25.40",
                "50.80",
                "76.20",
                "101.60",
                "127.00",
            ),
        )
    ]


def test_multi_site_mousewheel_scrolls_page_outside_nested_controls() -> None:
    class Notebook:
        def __init__(self, selected: object) -> None:
            self.selected = selected

        def select(self) -> str:
            return str(self.selected)

    class Widget:
        def __init__(self, x: int, y: int, width: int, height: int) -> None:
            self.bounds = (x, y, width, height)

        def winfo_rootx(self) -> int:
            return self.bounds[0]

        def winfo_rooty(self) -> int:
            return self.bounds[1]

        def winfo_width(self) -> int:
            return self.bounds[2]

        def winfo_height(self) -> int:
            return self.bounds[3]

    class Canvas(Widget):
        scrolls: list[tuple[int, str]] = []

        def yview_scroll(self, direction: int, units: str) -> None:
            self.scrolls.append((direction, units))

    class Event:
        num = None
        delta = -120

    app = object.__new__(RainwaterTkApp)
    app.import_tab = object()
    app.multi_site_rainwater_tab = object()
    app.notebook = Notebook(app.import_tab)
    app.rainwater_data_notebook = Notebook(app.multi_site_rainwater_tab)
    app.climate_normal_map = Widget(10, 300, 500, 200)
    app.climate_normal_state_list = Widget(10, 80, 150, 150)
    app.climate_normal_station_list = Widget(170, 80, 340, 150)
    app.climate_normal_tree = Widget(10, 550, 500, 150)
    app.multi_site_canvas = Canvas(0, 0, 600, 700)
    app.winfo_pointerxy = lambda: (550, 250)

    result = app._scroll_multi_site_mousewheel(Event())

    assert result == "break"
    assert app.multi_site_canvas.scrolls == [(1, "units")]


def test_multi_site_mousewheel_leaves_map_scrolling_to_map() -> None:
    app = object.__new__(RainwaterTkApp)
    app.import_tab = object()
    app.multi_site_rainwater_tab = object()
    app.notebook = type("Notebook", (), {"select": lambda _self: str(app.import_tab)})()
    app.rainwater_data_notebook = type(
        "Notebook", (), {"select": lambda _self: str(app.multi_site_rainwater_tab)}
    )()

    class Widget:
        def winfo_rootx(self) -> int:
            return 0

        def winfo_rooty(self) -> int:
            return 0

        def winfo_width(self) -> int:
            return 500

        def winfo_height(self) -> int:
            return 500

    app.climate_normal_map = Widget()
    app.climate_normal_state_list = Widget()
    app.climate_normal_station_list = Widget()
    app.climate_normal_tree = Widget()
    app.multi_site_canvas = Widget()
    app.winfo_pointerxy = lambda: (100, 100)

    assert app._scroll_multi_site_mousewheel(type("Event", (), {})()) is None


def test_multi_site_tab_info_icon_opens_help_without_selecting_tab() -> None:
    class Notebook:
        @staticmethod
        def index(tab: object) -> int:
            if isinstance(tab, str) and tab.startswith("@"):
                x = int(tab[1:].split(",", maxsplit=1)[0])
                return 2 if x < 400 else 3
            return 2

        @staticmethod
        def winfo_width() -> int:
            return 600

    class Event:
        x = 380
        y = 10

    app = object.__new__(RainwaterTkApp)
    app.rainwater_data_notebook = Notebook()
    app.multi_site_rainwater_tab = object()
    scheduled: list[object] = []
    app.after_idle = scheduled.append

    result = app._rainwater_data_notebook_clicked(Event())

    assert result == "break"
    assert scheduled == [app._show_multi_site_comparison_info]


def test_climate_normal_selection_does_not_duplicate_pending_request() -> None:
    class Variable:
        def __init__(self, value: str = "") -> None:
            self.value = value

        def get(self) -> str:
            return self.value

        def set(self, value: str) -> None:
            self.value = value

    class StationList:
        @staticmethod
        def curselection() -> tuple[int]:
            return (0,)

    class Button:
        def configure(self, **_kwargs: str) -> None:
            pass

    app = object.__new__(RainwaterTkApp)
    app.climate_normal_station_list = StationList()
    app.climate_normal_search_results = [
        {"station_id": "USW00013873", "name": "ATHENS BEN EPPS AP"}
    ]
    app.climate_normal_station_var = Variable()
    app.climate_normal_status_var = Variable()
    app.add_climate_normal_button = Button()
    app.climate_normal_detail_in_flight_ids = {"USW00013873"}
    app._update_climate_normal_map_selection = lambda: None

    app._climate_normal_station_selected()

    assert app.climate_normal_station_var.get() == "USW00013873"
    assert app.climate_normal_status_var.get() == (
        "The precipitation normals for ATHENS BEN EPPS AP are already loading."
    )


def test_report_surfaces_only_include_positive_areas() -> None:
    config = default_project_config()
    config.surfaces = [
        Surface("Used roof", area=1000.0, runoff_coefficient=0.9),
        Surface("Unused roof", area=0.0, runoff_coefficient=0.95),
        Surface("Invalid negative roof", area=-10.0, runoff_coefficient=0.8),
    ]

    rows = _report_surface_rows(config)

    assert [row["name"] for row in rows] == ["Used roof"]


def test_report_charts_mark_selected_tank_with_red_circle(tmp_path) -> None:
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
        "executive_summary": {
            "average_annual_supply": 120000.0,
            "average_annual_municipal_makeup": 45000.0,
            "average_annual_system_unmet": 0.0,
            "average_annual_overflow": 18000.0,
            "average_annual_first_flush_loss": 1200.0,
            "average_annual_treatment_loss": 500.0,
            "net_annual_savings": 420.0,
            "simple_payback_years": 12.5,
            "financial_configured": True,
        },
        "candidate_performance": [{
            "selected": True, "tank_size": 750.0, "reliability": 65.0,
            "RainwaterSuppliedGallons": 120000.0, "MunicipalMakeupGallons": 45000.0,
            "SystemUnmetDemandGallons": 0.0, "OverflowGallons": 18000.0,
            "FirstFlushLossGallons": 1200.0, "TreatmentLossGallons": 500.0,
            "FinalStorageGallons": 610.0, "NetAnnualSavings": 420.0,
            "SimplePaybackYears": 12.5,
        }],
        "recommendation_assumptions": {
            "reliability_target_percent": 80.0,
            "marginal_gain_threshold": 1.0,
        },
        "recommendations": [{
            "role": "Smallest tank meeting reliability target",
            "tank_size": 1000.0,
            "volume_unit": "gal",
            "reliability_percent": 75.0,
            "detail": "First candidate meeting the configured target.",
        }],
        "review_warnings": ["Rainfall record contains an incomplete calendar year."],
        "rainfall_quality": {
            "completeness_percent": 99.73, "completeness_rating": "Good",
            "expected_days": 731, "observed_days": 729, "missing_days": 2,
            "duplicate_dates": 0, "invalid_precipitation_rows": 0,
            "partial_years": [2024],
            "missing_periods": [{"start": "2024-03-04", "end": "2024-03-05", "days": 2}],
        },
        "yearly_rainfall_summary": [{
            "year": 2024, "expected_days": 366, "observed_days": 364,
            "missing_days": 2, "completeness_percent": 99.45,
            "precipitation": 42.25, "wet_days": 108, "partial_year": True,
        }],
        "rainfall_event_summary": {
            "event_count": 75, "average_event_precipitation": 0.563,
            "largest_event_precipitation": 3.25, "antecedent_dry_days": 1.0,
            "largest_events": [{
                "event_number": 31, "start": "2024-08-12", "end": "2024-08-13",
                "duration_days": 2, "wet_days": 2, "precipitation": 3.25,
            }],
        },
        "water_balance": {
            "potential_surface_rainfall": 250000.0, "runoff_coefficient_loss": 25000.0,
            "gross_runoff": 225000.0, "first_flush_loss": 2400.0,
            "net_collected": 222600.0, "initial_storage": 375.0,
            "rainwater_supplied": 200000.0, "treatment_loss": 1000.0,
            "overflow": 21365.0, "final_storage": 610.0,
            "collection_residual": 0.0, "storage_residual": 0.0,
        },
        "end_use_rows": [{
            "name": "Landscape irrigation", "type": "Irrigation system",
            "schedule": "Mon, Wed, Fri", "sewer_basis": "Exempt",
            "annual_demand": 90000.0, "annual_supply": 72000.0,
            "demand_met_percent": 80.0, "water_savings": 180.0, "sewer_savings": 0.0,
        }],
        "financial_summary": {
            "configured": True, "currency": "USD", "water_rate": 2.5,
            "sewer_rate": 3.0, "tariff_billing_unit": "per 1,000 gal",
            "legacy_sewer_eligible_percent": 100.0, "installed_cost": 6000.0,
            "incentives": 750.0, "fixed_annual_maintenance": 100.0,
            "annual_maintenance_percent": 1.0, "analysis_period_years": 20,
            "average_annual_supply": 120000.0, "average_annual_sewer_eligible_supply": 48000.0,
            "municipal_water_savings": 300.0, "sewer_savings": 144.0,
            "gross_annual_savings": 444.0, "annual_maintenance_cost": 160.0,
            "net_annual_savings": 284.0, "net_installed_cost": 5250.0,
            "simple_payback_years": 18.49, "analysis_period_net_benefit": 430.0,
            "discount_rate_percent": 5.0,
            "utility_rate_escalation_percent": 2.5,
            "maintenance_escalation_percent": 2.0,
            "electricity_escalation_percent": 2.0,
            "equipment_replacement_escalation_percent": 2.0,
            "average_annual_pump_energy_kwh": 420.0,
            "annual_pump_energy_cost": 63.0,
            "total_replacement_cost": 1500.0,
            "lifecycle_net_present_value": 825.0,
            "internal_rate_of_return_percent": 6.75,
            "discounted_payback_years": 19.2,
            "annual_cash_flows": [-5250.0, 281.0, 288.0],
            "methodology": "Discounted lifecycle cash-flow estimate based on simulated delivery.",
        },
        "provenance": {
            "rainfall_source": "Example station (TEST)", "record_start": "2024-01-01",
            "record_end": "2025-12-31", "calendar_years": 2, "observations": 731,
            "missing_calendar_days": 0, "rainfall_resolution": "Daily",
            "rainfall_data_type": "Observed station data",
            "rainfall_timezone": "America/New_York",
            "rainfall_timing_metadata": "Observed daily totals; within-day timing not observed",
            "rainfall_retrieved_at": "2026-07-18T10:30:00-04:00",
            "simulation_timestep": "Daily mass balance", "rainfall_timing_assumption": "Daily total",
            "system_type": "Indirect system", "municipal_backup": "Enabled",
            "initial_tank_fill_percent": 50.0, "filter_recovery_percent": 95.0,
            "application_version": "0.1.1", "algorithm_version": 12,
            "analysis_input_signature": "abc123", "generated_at": "2026-07-19T12:00:00+02:00",
        },
        "include_multitank_charts": True,
        "include_system_visualization": True,
        "system_type": "Indirect system",
        "project_latitude": 33.95,
        "project_longitude": -83.33,
        "weather_station_latitude": 33.94773,
        "weather_station_longitude": -83.32736,
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
    html_executive = html[html.index('id="executive-summary"'):html.index('id="notes"')]
    html_project_information = html[
        html.index('id="project-information"'):html.index('id="executive-summary"')
    ]
    latex_executive = latex[
        latex.index(r"\section{Executive Summary}"):latex.index(r"\section{Notes}")
    ]
    latex_project_information = latex[
        latex.index(r"\section{Project Information}"):latex.index(r"\section{Executive Summary}")
    ]
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
    assert "Executive design summary" in html
    assert "Precipitation basis" in html_executive
    assert "Rain only" in html_executive
    assert "Average annual precipitation" in html_executive
    assert "42.38 in" in html_executive
    assert "Precipitation basis" not in html_project_information
    assert "Average annual precipitation" not in html_project_information
    assert "Selected tank size" not in html_project_information
    assert "Selected tank reliability" not in html_project_information
    assert "Candidate tank performance" in html
    assert "Design recommendations and review conditions" in html
    assert "Smallest tank meeting reliability target" in html
    assert "Rainfall record contains an incomplete calendar year." in html
    assert "Reliability curve data" in html
    assert "Yearly demand reliability data" in html
    assert "Tank level distribution data" in html
    assert "data-sortable-table" in html
    assert "Reconciled water balance" in html
    assert "Less runoff-coefficient loss" in html
    assert "End-use demand and savings" in html
    assert "Landscape irrigation" in html
    assert "Financial assumptions and results" in html
    assert "Lifecycle net present value" in html
    assert "Internal rate of return" in html
    assert "420.0 kWh/year" in html
    assert "Annual lifecycle cash flow" in html
    assert "Cumulative discounted cash flow" in html
    assert "Annual lifecycle cash flow" in latex
    assert "Analysis provenance and reproducibility" in html
    assert "Example station (TEST)" in html
    assert "<h2>Tank summary</h2>" in html
    assert 'id="system-visualization"' in html
    assert "System visualization - Indirect system" in html
    assert "Filtration pump" in html
    assert "Booster pump" in html
    assert "Municipal water backup" in html
    assert 'id="project-location-map"' in html
    assert "Project location" in html
    assert "Weather station" in html
    assert "<dt>Project location coordinates</dt><dd>33.950000, -83.330000</dd>" in html
    assert "<dt>Weather station coordinates</dt><dd>33.947730, -83.327360</dd>" in html
    assert html.index("Project location coordinates") < html.index('id="project-location-map"')
    assert html.index("Weather station coordinates") < html.index('id="project-location-map"')
    assert "<caption>Location coordinates</caption>" not in html
    assert "tile.openstreetmap.org" in html
    assert '<image href="https://tile.openstreetmap.org/' in html
    assert "unpkg.com" not in html
    assert "Map data &copy; OpenStreetMap contributors" in html
    assert "Static map tiles require an internet connection" in html
    assert "Rainfall quality and completeness" in html
    assert "99.73% (Good)" in html
    assert "2024-03-04" in html
    assert "Yearly rainfall summary" in html
    assert "Rainfall-event summary" in html
    assert "Observed station data" in html
    assert "America/New_York" in html
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
    assert (
        html.index('id="project-information"')
        < html.index('id="executive-summary"')
        < html.index('id="notes"')
        < html.index('id="design-recommendations"')
    )
    assert "Coordinate with facilities.\nConfirm irrigation schedule." in html
    assert "<td>101</td><td>3,001</td>" in html
    assert "365,001 gal" in html
    assert "Produced by Jane Engineer" in html
    assert "Selected tank" in html_executive
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
    assert r"\section{Design Recommendations and Review Conditions}" in latex
    for section in (
        "Executive Summary",
        "Candidate Performance",
        "Reconciled Water Balance",
        "End-use Performance",
        "Financial Analysis",
        "Rainfall Quality and Completeness",
        "Yearly Rainfall Summary",
        "Rainfall-event Summary",
        "Analysis Provenance",
    ):
        assert rf"\section{{{section}}}" in latex
    assert "99.73" in latex
    assert "Observed station data" in latex
    assert r"America/New\_York" in latex
    assert "Smallest tank meeting reliability target" in latex
    assert "Rainfall record contains an incomplete calendar year." in latex
    assert r"\section{System Visualization - Indirect system}" in latex
    assert "Precipitation basis & Rain only" in latex_executive
    assert "Selected tank & 750 gal" in latex_executive
    assert "Selected reliability & 65.00\\%" in latex_executive
    assert "Average annual precipitation & 42.38 in" in latex_executive
    assert "Precipitation basis" not in latex_project_information
    assert "Average annual precipitation" not in latex_project_information
    assert "Selected tank size" not in latex_project_information
    assert "Selected tank reliability" not in latex_project_information
    assert r"\textbf{Project location coordinates} & 33.950000, -83.330000" in latex
    assert r"\textbf{Weather station coordinates} & 33.947730, -83.327360" in latex
    assert r"\section{Notes}" in latex
    assert (
        latex.index(r"\section{Project Information}")
        < latex.index(r"\section{Executive Summary}")
        < latex.index(r"\section{Notes}")
    )
    assert r"Coordinate with facilities.\par Confirm irrigation schedule." in latex
    assert "750 gal" in latex
    assert r"\section{Demand Summary}" in latex
    assert "365,001 gal" in latex
    assert r"\textbf{Produced by:} Jane Engineer" in latex
    assert "42.38 in" in latex
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

    pdf_path = tmp_path / "parity.pdf"
    app = object.__new__(RainwaterTkApp)
    app._write_fallback_pdf_report(pdf_path, ReportModel.from_payload(report))
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf_path).pages)
    pdf_executive = pdf_text[
        pdf_text.rindex("Executive Summary"):pdf_text.rindex("Notes")
    ]
    pdf_project_information = pdf_text[
        pdf_text.rindex("Project Information"):pdf_text.rindex("Executive Summary")
    ]
    assert (
        pdf_text.index("Project Information")
        < pdf_text.index("Executive Summary")
        < pdf_text.index("Notes")
    )
    assert "Design Recommendations" in pdf_text
    assert "Smallest tank meeting reliability target" in pdf_text
    assert "Rainfall record contains an incomplete calendar year." in pdf_text
    for section in (
        "Executive Summary",
        "Candidate Performance",
        "Reconciled Water Balance",
        "End-use Performance",
        "Financial Analysis",
        "Rainfall Quality and Completeness",
        "Yearly Rainfall Summary",
        "Rainfall-event Summary",
        "Analysis Provenance",
    ):
        assert section in pdf_text
    assert "Observed station data" in pdf_text
    assert "America/New_York" in pdf_text
    assert "Precipitation basis: Rain only" in pdf_executive
    assert "Selected tank: 750 gal" in pdf_executive
    assert "Selected reliability: 65.00%" in pdf_executive
    assert "Average annual precipitation: 42.38 in" in pdf_executive
    assert "Precipitation basis" not in pdf_project_information
    assert "Average annual precipitation" not in pdf_project_information
    assert "Selected tank size" not in pdf_project_information
    assert "Selected tank reliability" not in pdf_project_information
    assert "Project location coordinates:" in pdf_text
    assert "33.950000, -83.330000" in pdf_text
    assert "Weather station coordinates:" in pdf_text
    assert "33.947730, -83.327360" in pdf_text

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


def test_report_end_use_rows_allocate_supply_and_respect_sewer_exemption() -> None:
    config = default_project_config()
    config.demand.hourly_schedule_library["Always"] = {
        day: [1.0] * 24 for day in WEEKDAY_KEYS
    }
    config.demand.demand_objects = [DemandObject(
        "Irrigation", "Irrigation system", schedule_name="Always",
        demand_mode="recurring_daily", recurring_daily_gallons=100.0,
        operating_weekdays=list(range(7)), sewer_eligible=False,
    )]
    config.financial_parameters.water_rate = 10.0
    config.financial_parameters.sewer_rate = 20.0
    app = RainwaterTkApp.__new__(RainwaterTkApp)
    app.config_model = config
    app.results_df = pd.DataFrame({
        "Date": pd.to_datetime(["2025-01-06", "2025-01-07"]),
        "DemandGallons": [100.0, 100.0],
        "RainwaterSuppliedGallons": [50.0, 50.0],
    })

    rows = app._report_end_use_rows()

    assert len(rows) == 1
    assert rows[0]["annual_demand"] == pytest.approx(200.0)
    assert rows[0]["annual_supply"] == pytest.approx(100.0)
    assert rows[0]["demand_met_percent"] == pytest.approx(50.0)
    assert rows[0]["water_savings"] == pytest.approx(1.0)
    assert rows[0]["sewer_savings"] == 0.0
    assert rows[0]["sewer_basis"] == "Exempt"


def test_report_water_balance_reconciles_collection_and_storage() -> None:
    config = default_project_config()
    config.surfaces = [Surface("Roof", area=100.0, runoff_coefficient=0.9)]
    potential = 100.0 / 12.0 * 7.48051948
    gross = potential * 0.9
    initial = config.selected_tank_size_gal * 0.5
    app = RainwaterTkApp.__new__(RainwaterTkApp)
    app.config_model = config
    app.rainfall_df = pd.DataFrame({
        "Date": pd.to_datetime(["2025-01-01"]), "Precipitation": [1.0],
    })
    app.results_df = pd.DataFrame({
        "GrossCollectedGallons": [gross], "FirstFlushLossGallons": [0.0],
        "CollectedGallons": [gross], "RainwaterSuppliedGallons": [10.0],
        "FilterLossGallons": [0.0], "OverflowGallons": [0.0],
        "WaterInTankGallons": [initial + gross - 10.0],
    })

    balance = app._report_water_balance()

    assert balance["runoff_coefficient_loss"] == pytest.approx(potential * 0.1)
    assert balance["collection_residual"] == pytest.approx(0.0)
    assert balance["storage_residual"] == pytest.approx(0.0)


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


def test_animation_tank_label_shows_current_volume_and_capacity() -> None:
    imperial = default_project_config()
    metric = default_project_config()
    metric.unit_system = "Metric"

    assert _tank_volume_capacity_label(4654.0, 5000.0, imperial) == (
        "4,654 gal / 5,000 gal"
    )
    assert _tank_volume_capacity_label(4654.0, 5000.0, metric) == (
        "17,617 L / 18,927 L"
    )


def test_animation_overflow_connection_and_pipe_flow_labels() -> None:
    row = pd.Series({"OverflowGallons": 120.0})
    imperial = default_project_config()
    metric = default_project_config()
    metric.unit_system = "Metric"

    assert RainwaterTkApp._system_animation_connection_active(
        "primary_tank", "overflow_pipe", row
    )
    assert RainwaterTkApp._system_animation_connection_flow_gallons(
        "primary_tank", "overflow_pipe", row
    ) == pytest.approx(120.0)
    assert RainwaterTkApp._system_animation_pipe_flow_label(60.0, imperial) == "1.0 GPM"
    assert RainwaterTkApp._system_animation_pipe_flow_label(60.0, metric) == "3.8 LPM"


def test_reverse_system_connection_routes_around_object_bodies() -> None:
    points = RainwaterTkApp._system_connection_points(500.0, 180.0, 220.0, 180.0, 420.0)

    coordinate_pairs = list(zip(points[::2], points[1::2]))
    assert len(coordinate_pairs) == 6
    assert coordinate_pairs[0] == (565.0, 180.0)
    assert coordinate_pairs[-1] == (155.0, 180.0)
    assert any(y < 150.0 for _x, y in coordinate_pairs)
    assert coordinate_pairs[-2][0] < 155.0


def test_forward_system_connection_uses_compact_orthogonal_route() -> None:
    points = RainwaterTkApp._system_connection_points(100.0, 100.0, 400.0, 220.0, 420.0)

    assert len(points) == 8
    assert points[:2] == (165.0, 100.0)
    assert points[-2:] == (335.0, 220.0)


def test_reverse_connection_uses_gap_when_source_is_above_target() -> None:
    points = RainwaterTkApp._system_connection_points(500.0, 100.0, 220.0, 260.0, 420.0)
    coordinate_pairs = list(zip(points[::2], points[1::2]))

    assert coordinate_pairs == [
        (565.0, 100.0),
        (589.0, 100.0),
        (589.0, 180.0),
        (131.0, 180.0),
        (131.0, 260.0),
        (155.0, 260.0),
    ]


def test_close_forward_connection_never_uses_loop_route() -> None:
    points = RainwaterTkApp._system_connection_points(
        100.0, 100.0, 232.0, 125.0, 420.0
    )
    coordinate_pairs = list(zip(points[::2], points[1::2]))

    assert len(coordinate_pairs) == 4
    assert coordinate_pairs[0] == (165.0, 100.0)
    assert coordinate_pairs[-1] == (167.0, 125.0)
    assert all(
        coordinate_pairs[index][0] <= coordinate_pairs[index + 1][0]
        for index in range(len(coordinate_pairs) - 1)
    )


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


def test_booster_input_nodes_disconnect_independently() -> None:
    connections = [
        {"source_component": "rain", "target_component": "booster"},
        {
            "source_component": "mains", "target_component": "booster",
            "target_port": "in2",
        },
    ]

    assert RainwaterTkApp._connections_after_node_disconnect(
        connections, "booster", "in"
    ) == [connections[1]]
    assert RainwaterTkApp._connections_after_node_disconnect(
        connections, "booster", "in2"
    ) == [connections[0]]


def test_primary_output_nodes_disconnect_independently() -> None:
    connections = [
        {"source_component": "primary", "target_component": "pump"},
        {
            "source_component": "primary", "source_port": "out2",
            "target_component": "first_flush",
        },
    ]

    assert RainwaterTkApp._connections_after_node_disconnect(
        connections, "primary", "out"
    ) == [connections[1]]
    assert RainwaterTkApp._connections_after_node_disconnect(
        connections, "primary", "out2"
    ) == [connections[0]]


def test_first_flush_diversion_has_an_input_only() -> None:
    assert RainwaterTkApp._system_component_ports("first_flush_diversion") == (True, False)


def test_system_builder_zoom_moves_in_ten_percent_steps_with_three_step_limits() -> None:
    zoom = 1.0
    for _ in range(4):
        zoom = RainwaterTkApp._bounded_system_builder_zoom(zoom, -0.1)
    assert zoom == pytest.approx(0.7)

    zoom = 1.0
    for _ in range(4):
        zoom = RainwaterTkApp._bounded_system_builder_zoom(zoom, 0.1)
    assert zoom == pytest.approx(1.3)


def test_system_builder_pan_is_limited_to_maximum_zoom_out_workspace() -> None:
    assert RainwaterTkApp._bounded_system_builder_pan(
        700.0, 420.0, 0.7, -100.0, -100.0
    ) == pytest.approx((0.0, 0.0))

    pan = RainwaterTkApp._bounded_system_builder_pan(
        700.0, 420.0, 1.0, -1000.0, 100.0
    )
    assert pan == pytest.approx((-300.0, 0.0))


def test_system_builder_canvas_grows_to_contain_all_objects_and_ports() -> None:
    layout = [
        {"x": 100.0, "y": 100.0},
        {"x": 900.0, "y": 510.0, "width": 200.0, "height": 100.0},
    ]

    assert RainwaterTkApp._required_system_builder_canvas_size(layout) == (1032, 576)


def test_system_builder_canvas_keeps_its_useful_minimum_size() -> None:
    assert RainwaterTkApp._required_system_builder_canvas_size([]) == (760, 420)


def test_animation_flow_activity_uses_hourly_component_results() -> None:
    row = pd.Series({
        "CollectedGallons": 10.0,
        "PumpFlowGallons": 5.0,
        "FilterThroughputGallons": 4.0,
        "MainsMakeupGallons": 2.0,
        "DemandGallons": 3.0,
        "SystemUnmetDemandGallons": 0.0,
    })

    assert RainwaterTkApp._system_animation_connection_active(
        "rainwater_input", "primary_tank", row
    )
    assert RainwaterTkApp._system_animation_connection_active(
        "filtration_pump", "filtration_system", row
    )
    assert RainwaterTkApp._system_animation_connection_active(
        "municipal_backup", "booster_tank", row
    )
    assert RainwaterTkApp._system_animation_connection_active(
        "booster_pump", "end_uses", row
    )
    assert not RainwaterTkApp._system_animation_connection_active(
        "primary_tank", "first_flush_diversion", row
    )


def test_animation_weather_uses_collected_rainwater_for_current_hour() -> None:
    assert RainwaterTkApp._system_animation_rain_active(
        pd.Series({"CollectedGallons": 0.01})
    )
    assert not RainwaterTkApp._system_animation_rain_active(
        pd.Series({"CollectedGallons": 0.0})
    )


def test_animation_seconds_per_hour_are_bounded() -> None:
    assert RainwaterTkApp._bounded_system_animation_seconds(0.0) == pytest.approx(0.1)
    assert RainwaterTkApp._bounded_system_animation_seconds(2.5) == pytest.approx(2.5)
    assert RainwaterTkApp._bounded_system_animation_seconds(100.0) == pytest.approx(60.0)


def test_single_hour_animation_can_advance_or_loop() -> None:
    assert RainwaterTkApp._single_hour_animation_completion(
        5, "Advance to next hour"
    ) == (6, True)
    assert RainwaterTkApp._single_hour_animation_completion(
        5, "Loop current hour"
    ) == (5, False)
    assert RainwaterTkApp._single_hour_animation_completion(
        23, "Advance to next hour"
    ) == (23, True)


def test_animation_uses_smooth_but_bounded_frame_count() -> None:
    assert RainwaterTkApp._system_animation_frames_per_hour(1.0) == 25
    assert RainwaterTkApp._system_animation_frames_per_hour(2.0) == 50


def test_animation_can_select_the_next_available_day() -> None:
    dates = ("2025-01-01", "2025-01-02", "2025-01-04")

    assert RainwaterTkApp._next_system_animation_date(
        dates, "2025-01-01"
    ) == "2025-01-02"
    assert RainwaterTkApp._next_system_animation_date(
        dates, "2025-01-04"
    ) is None
    assert RainwaterTkApp._adjacent_system_animation_date(
        dates, "2025-01-02", -1
    ) == "2025-01-01"
    assert RainwaterTkApp._adjacent_system_animation_date(
        dates, "2025-01-01", -1
    ) is None


def test_irrigation_end_use_animation_follows_assignment_and_schedule() -> None:
    app = object.__new__(RainwaterTkApp)
    app.config_model = default_project_config()
    app.config_model.demand.demand_objects = [
        DemandObject("Garden", "Irrigation system", 2.0, "Morning")
    ]
    app.config_model.demand.hourly_schedule_library["Morning"] = {
        day: [1.0] + [0.0] * 23 for day in WEEKDAY_KEYS
    }
    end_use = {"demand_object_indices": [0]}

    assert app._system_animation_irrigation_active(
        end_use, pd.Timestamp("2025-01-01 00:00")
    )
    assert not app._system_animation_irrigation_active(
        end_use, pd.Timestamp("2025-01-01 01:00")
    )


def test_animation_drag_converts_screen_distance_to_model_distance() -> None:
    assert RainwaterTkApp._system_animation_drag_delta(
        100.0, -50.0, 2.0
    ) == pytest.approx((50.0, -25.0))


def test_new_demand_object_is_assigned_to_every_end_uses_block() -> None:
    app = object.__new__(RainwaterTkApp)
    app.config_model = default_project_config()
    app.config_model.demand.demand_objects = [
        DemandObject("Existing"), DemandObject("New demand")
    ]
    app.config_model.system_layout = [
        {
            "id": "uses-1", "component_type": "end_uses",
            "demand_object_indices": [0],
        },
        {"id": "uses-2", "component_type": "end_uses"},
        {"id": "tank", "component_type": "primary_tank"},
    ]

    app._assign_demand_object_to_end_uses(1)

    assert app.config_model.system_layout[0]["demand_object_indices"] == [0, 1]
    assert app.config_model.system_layout[1]["demand_object_indices"] == [1]
    assert "demand_object_indices" not in app.config_model.system_layout[2]
