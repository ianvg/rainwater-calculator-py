import pandas as pd
import pytest

from rainwater_app.acis import _parse_acis_number, default_complete_calendar_range
from rainwater_app.defaults import default_project_config, default_surface_runoff
from rainwater_app.engine import (
    AnalysisCancelledError,
    collection_balance_series,
    demand_series,
    reliability_curve,
    simulate_hourly_tank,
    simulate_tank,
)
from rainwater_app.models import (
    DemandObject, Surface, common_hourly_schedule_templates, migrate_legacy_demand_inputs,
)
from rainwater_app.rainfall import HOURLY_PRECIPITATION_COLUMNS
from rainwater_app.storage import SQLiteStore


def test_common_hourly_schedule_templates() -> None:
    templates = common_hourly_schedule_templates()

    assert all(hours == [1.0] * 24 for hours in templates["Always on"].values())
    assert all(sum(hours) == 0.0 for hours in templates["Always off"].values())
    business_hours = templates["8 AM to 5 PM weekdays"]
    assert business_hours["mon"][8:17] == [1.0] * 9
    assert sum(business_hours["mon"]) == pytest.approx(9.0)
    assert sum(business_hours["sat"]) == 0.0


def test_hourly_schedule_values_are_relative_zero_to_one_multipliers() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 30.0
    cfg.demand.hourly_schedule_enabled = True
    cfg.demand.hourly_weekly_fractions = {
        day: [1.0, 0.5] + [0.0] * 22 for day in cfg.demand.hourly_weekly_fractions
    }
    cfg.tank_parameters.initial_fill_percent = 100.0
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert result["DemandGallons"].iloc[0] == pytest.approx(20.0)
    assert result["DemandGallons"].iloc[1] == pytest.approx(10.0)
    assert result["DemandGallons"].iloc[2:].sum() == pytest.approx(0.0)


def test_hourly_result_start_date_warms_up_tank_state_without_returning_prior_days() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 100.0
    cfg.demand.hourly_weekly_fractions = {
        day: [1.0] + [0.0] * 23 for day in cfg.demand.hourly_weekly_fractions
    }
    cfg.tank_parameters.initial_fill_percent = 50.0
    rainfall = pd.DataFrame({
        "Date": pd.date_range("2025-01-01", periods=2, freq="D"),
        "Precipitation": [0.0, 0.0],
    })

    result = simulate_hourly_tank(
        cfg, rainfall, 5000.0, result_start_date=pd.Timestamp("2025-01-02")
    )

    assert len(result) == 24
    assert pd.Timestamp(result.iloc[0]["Date"]) == pd.Timestamp("2025-01-02 00:00:00")
    assert result.iloc[0]["PrimaryTankBeginningGallons"] == pytest.approx(2400.0)
    assert result.iloc[0]["WaterInTankGallons"] == pytest.approx(2300.0)


def test_hourly_simulation_collects_generated_rainfall_in_its_assigned_hour() -> None:
    cfg = default_project_config()
    cfg.use_synthetic_hourly_rainfall = True
    cfg.surfaces = [Surface("Roof", 1000.0, 1.0, 0.0)]
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [1.0]})
    for column in HOURLY_PRECIPITATION_COLUMNS:
        rainfall[column] = 0.0
    rainfall.loc[0, HOURLY_PRECIPITATION_COLUMNS[5]] = 1.0

    result = simulate_hourly_tank(cfg, rainfall, 10000.0)

    assert result.loc[5, "CollectedGallons"] > 0.0
    assert result.loc[23, "CollectedGallons"] == pytest.approx(0.0)
    assert result["CollectedGallons"].sum() == pytest.approx(
        1000.0 / 12.0 * 7.48052
    )


def test_hourly_simulation_ignores_generated_profile_when_option_is_off() -> None:
    cfg = default_project_config()
    cfg.use_synthetic_hourly_rainfall = False
    cfg.surfaces = [Surface("Roof", 1000.0, 1.0, 0.0)]
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [1.0]})
    for column in HOURLY_PRECIPITATION_COLUMNS:
        rainfall[column] = 0.0
    rainfall.loc[0, HOURLY_PRECIPITATION_COLUMNS[5]] = 1.0

    result = simulate_hourly_tank(cfg, rainfall, 10000.0)

    assert result.loc[5, "CollectedGallons"] == pytest.approx(0.0)
    assert result.loc[23, "CollectedGallons"] > 0.0


def test_hourly_simulation_accumulates_overflow_for_animation() -> None:
    cfg = default_project_config()
    cfg.surfaces = [Surface("Roof", 1000.0, 1.0, 0.0)]
    cfg.tank_parameters.initial_fill_percent = 100.0
    rainfall = pd.DataFrame({
        "Date": pd.date_range("2025-01-01", periods=2, freq="D"),
        "Precipitation": [1.0, 0.5],
    })

    result = simulate_hourly_tank(cfg, rainfall, 100.0)

    assert result["CumulativeOverflowGallons"].to_numpy() == pytest.approx(
        result["OverflowGallons"].cumsum().to_numpy()
    )
    assert result.iloc[-1]["CumulativeOverflowGallons"] > 0.0


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
    assert {
        "Date",
        "CollectedGallons",
        "OverflowGallons",
        "DemandGallons",
        "WaterInTankGallons",
        "ReliabilityPercent",
    }.issubset(out.columns)


def test_first_flush_is_only_diverted_on_first_day_of_multi_day_event() -> None:
    cfg = default_project_config()
    cfg.surfaces = [
        Surface(
            "Roof", area=1200.0, runoff_coefficient=1.0,
            first_flush_depth_inches=0.1,
        )
    ]
    cfg.first_flush_antecedent_dry_days = 3.0
    rainfall = pd.DataFrame({
        "Date": pd.date_range("2025-01-01", periods=3, freq="D"),
        "Precipitation": [0.05, 0.10, 0.20],
    })

    balance = collection_balance_series(cfg, rainfall)
    first_day_runoff = 1200.0 * 0.05 / 12.0 * 7.48052

    assert balance["RainfallEventStart"].tolist() == [True, False, False]
    assert balance["RainfallEventId"].tolist() == [1, 1, 1]
    assert balance["FirstFlushLossGallons"].sum() == pytest.approx(first_day_runoff)
    assert balance.loc[0, "CollectedGallons"] == pytest.approx(0.0)
    assert balance.loc[1, "FirstFlushLossGallons"] == pytest.approx(0.0)
    assert balance.loc[2, "FirstFlushLossGallons"] == pytest.approx(0.0)


def test_first_flush_applies_runoff_coefficient_after_subtracting_depth() -> None:
    cfg = default_project_config()
    cfg.surfaces = [Surface("Roof", 1000.0, 0.8, 0.05)]
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.10]})

    balance = collection_balance_series(cfg, rainfall)
    expected_loss = 1000.0 * 0.8 * 0.05 / 12.0 * 7.48052
    expected_net = 1000.0 * 0.8 * (0.10 - 0.05) / 12.0 * 7.48052

    assert balance.loc[0, "FirstFlushLossGallons"] == pytest.approx(expected_loss)
    assert balance.loc[0, "CollectedGallons"] == pytest.approx(expected_net)


def test_default_first_flush_event_resets_after_one_dry_day() -> None:
    cfg = default_project_config()
    cfg.surfaces = [Surface("Roof", 1000.0, 1.0, 0.05)]
    rainfall = pd.DataFrame({
        "Date": pd.date_range("2025-01-01", periods=4, freq="D"),
        "Precipitation": [0.10, 0.10, 0.0, 0.10],
    })

    balance = collection_balance_series(cfg, rainfall)

    assert cfg.first_flush_antecedent_dry_days == 1.0
    assert balance["RainfallEventStart"].tolist() == [True, False, False, True]
    assert balance["FirstFlushLossGallons"].iloc[[0, 3]].tolist() == pytest.approx(
        [1000.0 * 0.05 / 12.0 * 7.48052] * 2
    )


def test_first_flush_resets_after_antecedent_dry_period() -> None:
    cfg = default_project_config()
    cfg.surfaces = [Surface("Roof", 1000.0, 1.0, 0.05)]
    cfg.first_flush_antecedent_dry_days = 2.0
    rainfall = pd.DataFrame({
        "Date": pd.date_range("2025-01-01", periods=5, freq="D"),
        "Precipitation": [0.2, 0.0, 0.0, 0.2, 0.1],
    })

    balance = collection_balance_series(cfg, rainfall)

    assert balance["RainfallEventStart"].tolist() == [True, False, False, True, False]
    assert balance["FirstFlushLossGallons"].iloc[0] == pytest.approx(
        balance["FirstFlushLossGallons"].iloc[3]
    )
    assert balance["FirstFlushLossGallons"].iloc[4] == pytest.approx(0.0)


def test_first_flush_supports_an_hour_level_antecedent_dry_period() -> None:
    cfg = default_project_config()
    cfg.surfaces = [Surface("Roof", 1000.0, 1.0, 0.05)]
    cfg.first_flush_antecedent_dry_days = 12.0 / 24.0
    cfg.first_flush_antecedent_dry_unit = "hours"
    rainfall = pd.DataFrame({
        "Date": pd.to_datetime([
            "2025-01-01 00:00", "2025-01-01 06:00", "2025-01-01 13:00",
        ]),
        "Precipitation": [0.2, 0.0, 0.2],
    })

    balance = collection_balance_series(cfg, rainfall)

    assert balance["RainfallEventStart"].tolist() == [True, False, True]


def test_first_flush_is_separate_and_reconciles_to_gross_runoff() -> None:
    cfg = default_project_config()
    cfg.surfaces = [
        Surface("Small diverter", 500.0, 0.8, 0.02),
        Surface("Large diverter", 700.0, 0.9, 0.50),
    ]
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.1]})

    balance = collection_balance_series(cfg, rainfall)

    assert balance.loc[0, "GrossCollectedGallons"] == pytest.approx(
        balance.loc[0, "FirstFlushLossGallons"] + balance.loc[0, "CollectedGallons"]
    )
    assert balance.loc[0, "FirstFlushLossGallons"] > 0.0
    assert balance.loc[0, "CollectedGallons"] > 0.0


def test_hourly_first_flush_is_allocated_at_daily_rainfall_boundary() -> None:
    cfg = default_project_config()
    cfg.surfaces = [Surface("Roof", 1000.0, 1.0, 0.05)]
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.1]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert result["FirstFlushLossGallons"].iloc[:23].sum() == pytest.approx(0.0)
    assert result["FirstFlushLossGallons"].iloc[23] > 0.0
    assert result["GrossCollectedGallons"].sum() == pytest.approx(
        result["FirstFlushLossGallons"].sum() + result["CollectedGallons"].sum()
    )


def test_simulate_tank_records_water_above_capacity_as_overflow() -> None:
    cfg = default_project_config()
    for surface in cfg.surfaces:
        surface.area = 0.0
    cfg.surfaces[0].area = 1000.0
    cfg.surfaces[0].runoff_coefficient = 0.9
    cfg.tank_parameters.initial_fill_percent = 0.0
    rainfall = pd.DataFrame(
        {
            "Date": pd.date_range("2025-01-01", periods=2, freq="D"),
            "Precipitation": [1.0, 0.0],
        }
    )

    out = simulate_tank(cfg, rainfall, tank_size_gallons=100.0)

    assert out.loc[0, "OverflowGallons"] == pytest.approx(out.loc[0, "CollectedGallons"] - 100.0)
    assert out.loc[0, "WaterInTankGallons"] == pytest.approx(100.0)
    assert out.loc[1, "OverflowGallons"] == 0.0


def test_daily_rainfall_is_available_after_that_days_demand() -> None:
    cfg = default_project_config()
    for surface in cfg.surfaces:
        surface.area = 0.0
    cfg.surfaces[0].area = 1000.0
    cfg.surfaces[0].runoff_coefficient = 1.0
    cfg.demand.simple_daily_demand_gallons = 50.0
    cfg.tank_parameters.initial_fill_percent = 0.0
    rainfall = pd.DataFrame(
        {
            "Date": pd.date_range("2025-01-01", periods=2, freq="D"),
            "Precipitation": [1.0, 0.0],
        }
    )

    result = simulate_tank(cfg, rainfall, tank_size_gallons=100.0)

    assert not bool(result.loc[0, "DemandMet"])
    assert result.loc[0, "UnmetDemandGallons"] == 50.0
    assert result.loc[0, "WaterInTankGallons"] == 100.0
    assert bool(result.loc[1, "DemandMet"])
    assert result.loc[1, "WaterInTankGallons"] == 50.0


def test_daily_simulation_obeys_builder_collection_and_supply_paths() -> None:
    cfg = default_project_config()
    cfg.surfaces[0].area = 1000.0
    cfg.surfaces[0].runoff_coefficient = 1.0
    cfg.demand.simple_daily_demand_gallons = 10.0
    cfg.tank_parameters.initial_fill_percent = 100.0
    cfg.system_layout = [
        {"id": "rain", "component_type": "rainwater_input"},
        {"id": "tank", "component_type": "primary_tank"},
        {"id": "uses", "component_type": "end_uses"},
    ]
    cfg.system_connections = []
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [1.0]})

    disconnected = simulate_tank(cfg, rainfall, 100.0)
    cfg.system_connections = [
        {"source_component": "rain", "target_component": "tank"},
        {"source_component": "tank", "target_component": "uses"},
    ]
    connected = simulate_tank(cfg, rainfall, 100.0)

    assert disconnected["CollectedGallons"].sum() == pytest.approx(0.0)
    assert disconnected["UnmetDemandGallons"].sum() == pytest.approx(10.0)
    assert connected["CollectedGallons"].sum() > 0.0
    assert connected["UnmetDemandGallons"].sum() == pytest.approx(0.0)


def test_daily_simulation_applies_filter_recovery_from_builder_path() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 20.0
    cfg.tank_parameters.initial_fill_percent = 100.0
    cfg.system_parameters.filter_recovery_percent = 50.0
    cfg.system_layout = [
        {"id": "tank", "component_type": "primary_tank"},
        {"id": "pump", "component_type": "filtration_pump"},
        {"id": "filter", "component_type": "filtration_system"},
        {"id": "uses", "component_type": "end_uses"},
    ]
    cfg.system_connections = [
        {"source_component": "tank", "target_component": "pump"},
        {"source_component": "pump", "target_component": "filter"},
        {"source_component": "filter", "target_component": "uses"},
    ]
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    result = simulate_tank(cfg, rainfall, 100.0)

    assert result["UnmetDemandGallons"].sum() == pytest.approx(0.0)
    assert result["WaterInTankGallons"].iloc[-1] == pytest.approx(60.0)


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


def test_reliability_curve_candidate_metrics_reconcile_with_simulation() -> None:
    cfg = default_project_config()
    cfg.surfaces = [Surface("Roof", 800.0, 0.9, 0.04)]
    cfg.demand.simple_daily_demand_gallons = 60.0
    cfg.system_parameters.filter_recovery_percent = 80.0
    rainfall = pd.DataFrame({
        "Date": pd.date_range("2024-12-30", periods=5, freq="D"),
        "Precipitation": [0.2, 0.0, 0.1, 0.0, 0.3],
    })

    curve = reliability_curve(cfg, rainfall, [100.0, 250.0])
    candidate = curve.loc[curve["TankSizeGallons"] == 100.0].iloc[0]
    detailed = simulate_tank(cfg, rainfall, 100.0)

    assert candidate["ReliabilityPercent"] == pytest.approx(detailed["ReliabilityPercent"].iloc[0])
    assert candidate["TotalDemandGallons"] == pytest.approx(detailed["DemandGallons"].sum())
    assert candidate["RainwaterSuppliedGallons"] == pytest.approx(detailed["RainwaterSuppliedGallons"].sum())
    assert candidate["SewerEligibleRainwaterSuppliedGallons"] == pytest.approx(
        detailed["SewerEligibleRainwaterSuppliedGallons"].sum()
    )
    assert candidate["UnmetDemandGallons"] == pytest.approx(detailed["UnmetDemandGallons"].sum())
    assert candidate["MunicipalMakeupGallons"] == pytest.approx(detailed["MainsMakeupGallons"].sum())
    assert candidate["SystemUnmetDemandGallons"] == pytest.approx(detailed["SystemUnmetDemandGallons"].sum())
    assert candidate["OverflowGallons"] == pytest.approx(detailed["OverflowGallons"].sum())
    assert candidate["FirstFlushLossGallons"] == pytest.approx(detailed["FirstFlushLossGallons"].sum())
    assert candidate["TreatmentLossGallons"] == pytest.approx(detailed["FilterLossGallons"].sum())
    assert candidate["FinalStorageGallons"] == pytest.approx(detailed["WaterInTankGallons"].iloc[-1])
    assert candidate["AverageAnnualRainwaterSuppliedGallons"] == pytest.approx(
        detailed["RainwaterSuppliedGallons"].sum() / 2.0
    )


def test_reliability_curve_reports_numeric_candidate_progress() -> None:
    cfg = default_project_config()
    rainfall = pd.DataFrame({
        "Date": [pd.Timestamp("2025-01-01")],
        "Precipitation": [0.0],
    })
    progress: list[tuple[int, int, float]] = []

    reliability_curve(
        cfg,
        rainfall,
        [100.0, 200.0],
        progress_callback=lambda index, count, size: progress.append((index, count, size)),
    )

    assert progress == [(1, 2, 100.0), (2, 2, 200.0)]


def test_supplied_rainwater_is_allocated_by_end_use_for_sewer_savings() -> None:
    cfg = default_project_config()
    schedule_name = "Always on"
    cfg.demand.hourly_schedule_library[schedule_name] = common_hourly_schedule_templates()[schedule_name]
    cfg.demand.demand_objects = [
        DemandObject(
            "Toilets", "Toilet", schedule_name=schedule_name,
            demand_mode="recurring_daily", recurring_daily_gallons=50.0,
        ),
        DemandObject(
            "Landscape", "Irrigation system", schedule_name=schedule_name,
            demand_mode="recurring_daily", recurring_daily_gallons=50.0,
        ),
    ]
    cfg.tank_parameters.initial_fill_percent = 100.0
    rainfall = pd.DataFrame({
        "Date": [pd.Timestamp("2025-01-01")],
        "Precipitation": [0.0],
    })

    result = simulate_tank(cfg, rainfall, tank_size_gallons=50.0)

    assert cfg.demand.demand_objects[0].sewer_eligible is True
    assert cfg.demand.demand_objects[1].sewer_eligible is False
    assert result.loc[0, "DemandGallons"] == pytest.approx(100.0)
    assert result.loc[0, "RainwaterSuppliedGallons"] == pytest.approx(50.0)
    assert result.loc[0, "SewerEligibleDemandGallons"] == pytest.approx(50.0)
    assert result.loc[0, "SewerEligibleRainwaterSuppliedGallons"] == pytest.approx(25.0)


def test_hourly_sewer_eligible_supply_respects_demand_object_setting() -> None:
    cfg = default_project_config()
    schedule_name = "Always on"
    cfg.demand.hourly_schedule_library[schedule_name] = common_hourly_schedule_templates()[schedule_name]
    cfg.demand.active_hourly_schedule_name = schedule_name
    cfg.demand.demand_objects = [
        DemandObject("Indoor", "Other indoor", 1.0, schedule_name),
        DemandObject("Irrigation", "Irrigation system", 1.0, schedule_name),
    ]
    cfg.tank_parameters.initial_fill_percent = 100.0
    rainfall = pd.DataFrame({
        "Date": [pd.Timestamp("2025-01-01")],
        "Precipitation": [0.0],
    })

    result = simulate_hourly_tank(cfg, rainfall, tank_size_gallons=2_880.0)

    assert result["RainwaterSuppliedGallons"].sum() == pytest.approx(2_880.0)
    assert result["SewerEligibleRainwaterSuppliedGallons"].sum() == pytest.approx(1_440.0)


def test_migrated_demand_object_uses_legacy_sewer_percentage() -> None:
    cfg = default_project_config()
    schedule_name = "Always on"
    cfg.demand.hourly_schedule_library[schedule_name] = common_hourly_schedule_templates()[schedule_name]
    migrated = DemandObject(
        "Legacy demand", "Other", schedule_name=schedule_name,
        demand_mode="recurring_daily", recurring_daily_gallons=100.0,
    )
    migrated.uses_legacy_sewer_eligibility = True
    cfg.demand.demand_objects = [migrated]
    cfg.financial_parameters.sewer_eligible_percent = 35.0
    cfg.tank_parameters.initial_fill_percent = 100.0
    rainfall = pd.DataFrame({
        "Date": [pd.Timestamp("2025-01-01")],
        "Precipitation": [0.0],
    })

    result = simulate_tank(cfg, rainfall, tank_size_gallons=100.0)

    assert result.loc[0, "SewerEligibleRainwaterSuppliedGallons"] == pytest.approx(35.0)


def test_recurring_demand_uses_explicit_operating_weekdays() -> None:
    cfg = default_project_config()
    schedule_name = "Always on"
    cfg.demand.hourly_schedule_library[schedule_name] = common_hourly_schedule_templates()[schedule_name]
    cfg.demand.demand_objects = [DemandObject(
        "Weekend demand", "Other", schedule_name=schedule_name,
        demand_mode="recurring_daily", recurring_daily_gallons=25.0,
        operating_weekdays=[5, 6],
    )]
    rainfall = pd.DataFrame({
        "Date": pd.date_range("2025-01-03", periods=4, freq="D"),
        "Precipitation": [0.0] * 4,
    })

    assert demand_series(cfg, rainfall).tolist() == pytest.approx([0.0, 25.0, 25.0, 0.0])


def test_minimum_operating_level_protects_primary_tank_storage() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 100.0
    cfg.tank_parameters.initial_fill_percent = 100.0
    cfg.tank_parameters.minimum_operating_volume_percent = 50.0
    rainfall = pd.DataFrame(
        {
            "Date": pd.date_range("2025-01-01", periods=1, freq="D"),
            "Precipitation": [0.0],
        }
    )

    result = simulate_tank(cfg, rainfall, tank_size_gallons=100.0)

    assert not bool(result.loc[0, "DemandMet"])
    assert result.loc[0, "UnmetDemandGallons"] == 50.0
    assert result.loc[0, "WaterInTankGallons"] == 50.0
    assert result.loc[0, "MinimumOperatingVolumeGallons"] == 50.0
    assert result.loc[0, "UsableWaterAvailableGallons"] == 0.0
    assert result.loc[0, "ReliabilityPercent"] == 0.0


def test_hourly_simulation_respects_primary_tank_minimum_operating_level() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 2400.0
    cfg.demand.hourly_schedule_enabled = True
    cfg.tank_parameters.initial_fill_percent = 100.0
    cfg.tank_parameters.minimum_operating_volume_percent = 50.0
    rainfall = pd.DataFrame(
        {"Date": pd.to_datetime(["2025-01-01"]), "Precipitation": [0.0]}
    )

    result = simulate_hourly_tank(cfg, rainfall, tank_size_gallons=100.0)

    assert result["WaterInTankGallons"].min() == 50.0
    assert result["MinimumOperatingVolumeGallons"].eq(50.0).all()
    assert result["UnmetDemandGallons"].sum() == pytest.approx(2350.0)


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


def test_legacy_aggregate_demand_migrates_without_changing_daily_totals() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 25.0
    cfg.demand.daily_demand_days_per_week = 5
    cfg.demand.avg_flush_per_person = 3.0
    cfg.demand.gallons_per_flush_toilet = 1.2
    cfg.demand.gallons_per_flush_urinal = 0.5
    cfg.demand.male_occupancy["jan"] = 4.0
    cfg.demand.female_occupancy["jan"] = 5.0
    cfg.demand.spray_irrigation["jan"] = 310.0
    rainfall = pd.DataFrame({
        "Date": pd.date_range("2025-01-01", periods=7),
        "Precipitation": [0.0] * 7,
    })
    before = demand_series(cfg, rainfall)

    created = migrate_legacy_demand_inputs(cfg.demand)
    after = demand_series(cfg, rainfall)

    assert created
    assert after.tolist() == pytest.approx(before.tolist())
    hourly = simulate_hourly_tank(cfg, rainfall, tank_size_gallons=1000.0)
    assert hourly["DemandGallons"].sum() == pytest.approx(before.sum())
    assert cfg.demand.simple_daily_demand_gallons == 0.0
    assert cfg.demand.spray_irrigation["jan"] == 0.0
    assert migrate_legacy_demand_inputs(cfg.demand) == []


def test_daily_demand_schedule_applies_recurring_demand_on_selected_weekdays() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 125.0
    cfg.demand.daily_demand_days_per_week = 5
    rainfall = pd.DataFrame(
        {
            "Date": pd.date_range("2025-03-03", periods=7, freq="D"),
            "Precipitation": [0.0] * 7,
        }
    )

    demand = demand_series(cfg, rainfall)

    assert demand.tolist() == [125.0, 125.0, 125.0, 125.0, 125.0, 0.0, 0.0]


def test_demand_object_contributes_only_on_days_enabled_by_its_schedule() -> None:
    cfg = default_project_config()
    cfg.demand.hourly_schedule_library["Weekdays"] = {
        day: ([1.0] + [0.0] * 23) if day not in {"sat", "sun"} else [0.0] * 24
        for day in cfg.demand.hourly_weekly_fractions
    }
    cfg.demand.demand_objects = [DemandObject("Irrigation", "Irrigation system", 80.0, "Weekdays")]
    rainfall = pd.DataFrame(
        {"Date": pd.date_range("2025-03-03", periods=7, freq="D"), "Precipitation": [0.0] * 7}
    )

    assert demand_series(cfg, rainfall).tolist() == [4800.0, 4800.0, 4800.0, 4800.0, 4800.0, 0.0, 0.0]


def test_hourly_demand_object_uses_its_own_project_schedule() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 24.0
    cfg.demand.hourly_schedule_library = {
        "Morning": {day: [1.0] + [0.0] * 23 for day in cfg.demand.hourly_weekly_fractions},
        "Evening": {day: [0.0] * 23 + [1.0] for day in cfg.demand.hourly_weekly_fractions},
    }
    cfg.demand.active_hourly_schedule_name = "Morning"
    cfg.demand.demand_objects = [DemandObject("Cooling", "Cooling tower", 10.0, "Evening")]
    cfg.tank_parameters.initial_fill_percent = 100.0
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-03-03")], "Precipitation": [0.0]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert result["DemandGallons"].iloc[0] == pytest.approx(24.0)
    assert result["DemandGallons"].iloc[1:23].sum() == pytest.approx(0.0)
    assert result["DemandGallons"].iloc[23] == pytest.approx(600.0)


def test_old_saved_project_payload_defaults_simple_daily_demand() -> None:
    cfg = SQLiteStore._config_from_dict({"name": "Old Project", "demand": {}})

    assert cfg.demand.simple_daily_demand_gallons == 0.0
    assert cfg.demand.daily_demand_days_per_week == 7


def test_default_surface_runoff_values_match_named_surfaces() -> None:
    cfg = default_project_config()
    default_runoff = {surface.name: surface.runoff_coefficient for surface in cfg.surfaces}

    assert default_runoff["Roof membrane"] == 0.95
    assert default_runoff["Roof asphalt shingle"] == 0.9
    assert default_runoff["Roof metal"] == 0.95
    assert default_surface_runoff("Roof Membrane") == 0.95


def test_surface_runoff_coefficient_is_rounded_half_up_to_two_decimal_places() -> None:
    assert Surface("Test surface", runoff_coefficient=0.954).runoff_coefficient == 0.95
    assert Surface("Test surface", runoff_coefficient=0.955).runoff_coefficient == 0.96


def test_project_can_be_saved_without_rainfall_data(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "projects.db"))
    cfg = default_project_config()
    cfg.name = "No Rainfall Yet"

    store.save_project(cfg)

    loaded_cfg, rainfall = store.load_project("No Rainfall Yet")

    assert loaded_cfg.name == "No Rainfall Yet"
    assert rainfall.empty
    assert list(rainfall.columns) == ["Date", "Precipitation"]


def test_project_persists_rainfall_source_label(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "projects.db"))
    cfg = default_project_config()
    cfg.name = "ACIS Project"
    cfg.street_address = "1121 Brittain Estates Drive"
    cfg.city = "Kingsport"
    cfg.state_or_province = "Tennessee"
    cfg.postal_code = "37664"
    cfg.latitude = 36.548921
    cfg.longitude = -82.456789
    cfg.rainfall_source_label = "CENTRAL PARK NY (123456)"
    rainfall = pd.DataFrame(
        {
            "Date": pd.date_range("2025-01-01", periods=2, freq="D"),
            "Precipitation": [0.1, 0.0],
        }
    )

    store.save_project(cfg, rainfall)

    loaded_cfg, loaded_rainfall = store.load_project("ACIS Project")

    assert loaded_cfg.rainfall_source_label == "CENTRAL PARK NY (123456)"
    assert loaded_cfg.street_address == "1121 Brittain Estates Drive"
    assert loaded_cfg.city == "Kingsport"
    assert loaded_cfg.state_or_province == "Tennessee"
    assert loaded_cfg.postal_code == "37664"
    assert loaded_cfg.latitude == 36.548921
    assert loaded_cfg.longitude == -82.456789
    assert len(loaded_rainfall) == 2


def test_project_persists_analysis_outputs(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "projects.db"))
    cfg = default_project_config()
    cfg.name = "Analyzed Project"
    rainfall = pd.DataFrame(
        {
            "Date": pd.date_range("2025-01-01", periods=3, freq="D"),
            "Precipitation": [0.2, 0.0, 0.1],
        }
    )
    curve = pd.DataFrame(
        {
            "TankSizeGallons": [500.0, 1000.0],
            "ReliabilityPercent": [50.0, 75.0],
        }
    )
    results = simulate_tank(cfg, rainfall, 1000.0)
    comparison_results = simulate_tank(cfg, rainfall, 500.0)
    comparison_results["ComparisonTankSizeGallons"] = 500.0
    hourly_results = simulate_hourly_tank(cfg, rainfall, 1000.0)

    store.save_project(cfg, rainfall, curve, results, comparison_results, hourly_results)

    loaded_cfg, loaded_rainfall, loaded_curve, loaded_results = store.load_project_with_analysis("Analyzed Project")

    assert loaded_cfg.name == "Analyzed Project"
    assert len(loaded_rainfall) == 3
    assert loaded_curve["ReliabilityPercent"].tolist() == [50.0, 75.0]
    assert not loaded_results.empty
    assert "WaterInTankGallons" in loaded_results
    loaded_comparison_results = store.load_comparison_results("Analyzed Project")
    assert loaded_comparison_results["ComparisonTankSizeGallons"].tolist() == [500.0, 500.0, 500.0]
    loaded_hourly_results = store.load_hourly_results("Analyzed Project")
    assert len(loaded_hourly_results) == 72
    assert "WaterInTankGallons" in loaded_hourly_results


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


def test_simulation_can_be_cancelled_cooperatively() -> None:
    cfg = default_project_config()
    rainfall = pd.DataFrame(
        {"Date": pd.date_range("2025-01-01", periods=365), "Precipitation": [0.0] * 365}
    )

    with pytest.raises(AnalysisCancelledError, match="cancelled"):
        simulate_tank(cfg, rainfall, 1000.0, cancel_callback=lambda: True)


def test_reliability_curve_can_be_cancelled_before_first_tank() -> None:
    cfg = default_project_config()
    rainfall = pd.DataFrame(
        {"Date": pd.date_range("2025-01-01", periods=5), "Precipitation": [0.0] * 5}
    )

    with pytest.raises(AnalysisCancelledError, match="cancelled"):
        reliability_curve(cfg, rainfall, [500.0, 1000.0], cancel_callback=lambda: True)


def test_hourly_simulation_uses_typical_week_demand_profile() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 24.0
    cfg.demand.hourly_schedule_enabled = True
    cfg.demand.hourly_weekly_fractions["wed"] = [1.0] + [0.0] * 23
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert len(result) == 24
    assert result["DemandGallons"].iloc[0] == pytest.approx(24.0)
    assert result["DemandGallons"].iloc[1:].sum() == pytest.approx(0.0)


def test_hourly_rainfall_is_added_after_hour_23_demand() -> None:
    cfg = default_project_config()
    cfg.surfaces[0].area = 1000.0
    cfg.surfaces[0].runoff_coefficient = 1.0
    cfg.demand.simple_daily_demand_gallons = 24.0
    cfg.demand.hourly_weekly_fractions["wed"] = [1.0 / 24.0] * 24
    cfg.tank_parameters.initial_fill_percent = 0.0
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [1.0]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert result["CollectedGallons"].iloc[:23].sum() == pytest.approx(0.0)
    assert result["CollectedGallons"].iloc[23] > 0.0
    assert result["MainsMakeupGallons"].sum() == pytest.approx(24.0)
    assert result["WaterInTankGallons"].iloc[23] > 0.0


def test_custom_builder_rain_input_only_emits_through_a_connected_path() -> None:
    cfg = default_project_config()
    cfg.surfaces[0].area = 1000.0
    cfg.surfaces[0].runoff_coefficient = 1.0
    cfg.tank_parameters.initial_fill_percent = 0.0
    cfg.system_layout = [
        {"id": "rain", "component_type": "rainwater_input"},
        {"id": "tank", "component_type": "primary_tank"},
    ]
    cfg.system_connections = []
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [1.0]})

    disconnected = simulate_hourly_tank(cfg, rainfall, 1000.0)
    cfg.system_connections = [{"source_component": "rain", "target_component": "tank"}]
    connected = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert disconnected["CollectedGallons"].sum() == pytest.approx(0.0)
    assert disconnected["WaterInTankGallons"].iloc[-1] == pytest.approx(0.0)
    assert connected["CollectedGallons"].sum() > 0.0
    assert connected["WaterInTankGallons"].iloc[-1] > 0.0


def test_custom_builder_connections_govern_demand_delivery() -> None:
    cfg = default_project_config()
    cfg.system_type = "Indirect system"
    cfg.demand.simple_daily_demand_gallons = 24.0
    cfg.tank_parameters.initial_fill_percent = 100.0
    cfg.system_parameters.municipal_backup_enabled = False
    cfg.system_layout = [
        {"id": "tank", "component_type": "primary_tank"},
        {"id": "pump", "component_type": "booster_pump"},
        {"id": "uses", "component_type": "end_uses"},
    ]
    cfg.system_connections = [
        {"source_component": "tank", "target_component": "pump"},
        {"source_component": "pump", "target_component": "uses"},
    ]
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    connected = simulate_hourly_tank(cfg, rainfall, 1000.0)
    cfg.system_connections.pop()
    disconnected = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert connected["PumpFlowGallons"].sum() == pytest.approx(24.0)
    assert set(connected["SystemType"]) == {"Custom direct system"}
    assert disconnected["PumpFlowGallons"].sum() == pytest.approx(0.0)
    assert disconnected["SystemUnmetDemandGallons"].sum() == pytest.approx(24.0)


def test_custom_direct_pump_block_applies_its_capacity() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 24.0
    cfg.tank_parameters.initial_fill_percent = 100.0
    cfg.system_parameters.pump_capacity_gallons_per_hour = 0.5
    cfg.system_layout = [
        {"id": "tank", "component_type": "primary_tank"},
        {"id": "pump", "component_type": "booster_pump"},
        {"id": "uses", "component_type": "end_uses"},
    ]
    cfg.system_connections = [
        {"source_component": "tank", "target_component": "pump"},
        {"source_component": "pump", "target_component": "uses"},
    ]
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert result["PumpFlowGallons"].sum() == pytest.approx(12.0)


def test_indirect_hourly_results_report_filter_throughput() -> None:
    cfg = default_project_config()
    cfg.system_type = "Indirect system"
    cfg.demand.simple_daily_demand_gallons = 24.0
    cfg.tank_parameters.initial_fill_percent = 100.0
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert result["FilterThroughputGallons"].sum() == pytest.approx(24.0)
    assert set(result["SystemType"]) == {"Indirect system"}


def test_direct_hourly_pump_capacity_limits_rainwater_delivery() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 24.0
    cfg.tank_parameters.initial_fill_percent = 100.0
    cfg.system_parameters.pump_capacity_gallons_per_hour = 0.5
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert result["PumpFlowGallons"].sum() == pytest.approx(12.0)
    assert result["UnmetDemandGallons"].sum() == pytest.approx(12.0)
    assert result["MainsMakeupGallons"].sum() == pytest.approx(12.0)


def test_indirect_filter_recovery_records_water_loss() -> None:
    cfg = default_project_config()
    cfg.system_type = "Indirect system"
    cfg.demand.simple_daily_demand_gallons = 24.0
    cfg.tank_parameters.initial_fill_percent = 100.0
    cfg.system_parameters.filter_recovery_percent = 50.0
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert result["PumpFlowGallons"].sum() == pytest.approx(48.0)
    assert result["FilterThroughputGallons"].sum() == pytest.approx(24.0)
    assert result["FilterLossGallons"].sum() == pytest.approx(24.0)


def test_booster_storage_and_disabled_mains_are_applied() -> None:
    cfg = default_project_config()
    cfg.system_type = "Indirect system"
    cfg.demand.simple_daily_demand_gallons = 24.0
    cfg.tank_parameters.initial_fill_percent = 0.0
    cfg.system_parameters.booster_tank_size_gallons = 10.0
    cfg.system_parameters.booster_initial_fill_percent = 100.0
    cfg.system_parameters.municipal_backup_enabled = False
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert result["UnmetDemandGallons"].sum() == pytest.approx(14.0)
    assert result["MainsMakeupGallons"].sum() == pytest.approx(0.0)
    assert result["SystemUnmetDemandGallons"].sum() == pytest.approx(14.0)


def test_indirect_booster_refill_cycles_from_setpoint_until_full() -> None:
    cfg = default_project_config()
    cfg.system_type = "Indirect system"
    cfg.demand.simple_daily_demand_gallons = 60.0
    cfg.demand.hourly_weekly_fractions = {
        day: [1.0] + [0.0] * 23 for day in cfg.demand.hourly_weekly_fractions
    }
    cfg.tank_parameters.initial_fill_percent = 100.0
    cfg.system_parameters.booster_tank_size_gallons = 100.0
    cfg.system_parameters.booster_initial_fill_percent = 100.0
    cfg.system_parameters.booster_refill_level_percent = 50.0
    cfg.system_parameters.filtration_pump_capacity_gallons_per_hour = 10.0
    cfg.system_parameters.municipal_backup_enabled = False
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert result["PumpFlowGallons"].iloc[0] == pytest.approx(0.0)
    assert result["BoosterTankGallons"].iloc[0] == pytest.approx(40.0)
    assert result["PumpFlowGallons"].iloc[1:7].tolist() == pytest.approx([10.0] * 6)
    assert result["BoosterTankGallons"].iloc[6] == pytest.approx(100.0)
    assert result["PumpFlowGallons"].iloc[7:].sum() == pytest.approx(0.0)


def test_indirect_municipal_makeup_refills_booster_when_primary_is_empty() -> None:
    cfg = default_project_config()
    cfg.system_type = "Indirect system"
    cfg.demand.simple_daily_demand_gallons = 10.0
    cfg.demand.hourly_weekly_fractions = {
        day: [1.0] + [0.0] * 23 for day in cfg.demand.hourly_weekly_fractions
    }
    cfg.tank_parameters.initial_fill_percent = 0.0
    cfg.system_parameters.booster_tank_size_gallons = 100.0
    cfg.system_parameters.booster_initial_fill_percent = 0.0
    cfg.system_parameters.booster_refill_level_percent = 50.0
    cfg.system_parameters.filtration_pump_capacity_gallons_per_hour = 20.0
    cfg.system_parameters.municipal_backup_enabled = True
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert result["MainsMakeupGallons"].sum() == pytest.approx(110.0)
    assert result["MainsSuppliedGallons"].sum() == pytest.approx(10.0)
    assert result["SystemUnmetDemandGallons"].sum() == pytest.approx(0.0)
    assert not bool(result["DemandMet"].iloc[0])
    assert result["BoosterTankGallons"].iloc[5] == pytest.approx(100.0)


def test_hourly_simulation_uses_active_schedule_from_library() -> None:
    cfg = default_project_config()
    cfg.demand.simple_daily_demand_gallons = 24.0
    cfg.demand.hourly_schedule_library = {
        "Morning": {day: [1.0] + [0.0] * 23 for day in cfg.demand.hourly_weekly_fractions},
        "Evening": {day: [0.0] * 23 + [1.0] for day in cfg.demand.hourly_weekly_fractions},
    }
    cfg.demand.active_hourly_schedule_name = "Evening"
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    result = simulate_hourly_tank(cfg, rainfall, 1000.0)

    assert result["DemandGallons"].iloc[:23].sum() == pytest.approx(0.0)
    assert result["DemandGallons"].iloc[23] == pytest.approx(24.0)
