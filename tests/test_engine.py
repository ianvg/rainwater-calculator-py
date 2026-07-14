import pandas as pd

from rainwater_app.acis import _parse_acis_number, default_complete_calendar_range
from rainwater_app.defaults import default_project_config
from rainwater_app.engine import demand_series, reliability_curve, simulate_tank
from rainwater_app.storage import SQLiteStore


def test_simulate_tank_returns_expected_columns() -> None:
    cfg = default_project_config()
    cfg.surfaces[0].area = 1000
    cfg.surfaces[0].runoff_coefficient = 0.9

    rainfall = pd.DataFrame(
        {
            "Date": pd.date_range("2025-01-01", periods=5, freq="D"),
            "Precipitation": [0.5, 0.0, 0.2, 0.0, 0.3],
        }
    )

    out = simulate_tank(cfg, rainfall, tank_size_gallons=1000)

    assert not out.empty
    assert {"Date", "CollectedGallons", "DemandGallons", "WaterInTankGallons", "ReliabilityPercent"}.issubset(out.columns)


def test_default_acis_range_uses_complete_calendar_years() -> None:
    start, end = default_complete_calendar_range(years=30, today=pd.Timestamp("2026-07-03").date())

    assert start.isoformat() == "1996-01-01"
    assert end.isoformat() == "2025-12-31"


def test_acis_number_parser_handles_trace_and_flags() -> None:
    assert _parse_acis_number("T") == 0.0
    assert _parse_acis_number("M") == 0.0
    assert _parse_acis_number("0.12 A") == 0.12


def test_reliability_curve_bounds() -> None:
    cfg = default_project_config()
    cfg.surfaces[0].area = 500
    rainfall = pd.DataFrame(
        {
            "Date": pd.date_range("2025-02-01", periods=10, freq="D"),
            "Precipitation": [0.1] * 10,
        }
    )

    curve = reliability_curve(cfg, rainfall, [500, 1000, 2000])

    assert len(curve) == 3
    assert curve["ReliabilityPercent"].between(0, 100).all()


def test_simple_daily_demand_is_added_to_daily_demand() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 125.0
    rainfall = pd.DataFrame(
        {
            "Date": pd.date_range("2025-03-01", periods=3, freq="D"),
            "Precipitation": [0.0, 0.0, 0.0],
        }
    )

    demand = demand_series(cfg, rainfall)

    assert demand.tolist() == [125.0, 125.0, 125.0]


def test_old_saved_project_payload_defaults_simple_daily_demand() -> None:
    cfg = SQLiteStore._config_from_dict({"name": "Old Project", "demand": {}})

    assert cfg.demand.simple_daily_demand_gallons == 0.0


def test_project_can_be_saved_without_rainfall_data(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "projects.db"))
    cfg = default_project_config()
    cfg.name = "No Rainfall Yet"

    store.save_project(cfg)

    loaded_cfg, rainfall = store.load_project("No Rainfall Yet")

    assert loaded_cfg.name == "No Rainfall Yet"
    assert rainfall.empty
    assert list(rainfall.columns) == ["Date", "Precipitation"]


def test_reliability_curve_does_not_decrease_with_larger_tanks() -> None:
    cfg = default_project_config()
    cfg.surfaces[0].area = 2000
    cfg.surfaces[0].runoff_coefficient = 0.9
    cfg.demand.other_indoor = {month: 3000.0 for month in cfg.demand.other_indoor}
    cfg.tank_parameters.initial_fill_percent = 0.0

    rainfall = pd.DataFrame(
        {
            "Date": pd.date_range("2025-01-01", periods=30, freq="D"),
            "Precipitation": [1.0 if i % 10 == 0 else 0.0 for i in range(30)],
        }
    )

    curve = reliability_curve(cfg, rainfall, [500, 1000, 2000, 5000])

    assert curve["ReliabilityPercent"].is_monotonic_increasing
    assert curve["ReliabilityPercent"].iloc[-1] > curve["ReliabilityPercent"].iloc[0]
