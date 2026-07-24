import json
from pathlib import Path
import sqlite3

import pytest
import pandas as pd

from rainwater_app.defaults import default_project_config
from rainwater_app.rainfall import (
    HOURLY_PRECIPITATION_COLUMNS,
    disaggregate_daily_rainfall_hyetos,
    has_hourly_rainfall,
)
from rainwater_app.models import OCCUPANCY_SCHEDULE_TYPE
from rainwater_app.storage import (
    PROJECT_SCHEMA_VERSION,
    STORAGE_SCHEMA_VERSION,
    SQLiteStore,
)


def test_legacy_project_defaults_to_united_states() -> None:
    config = SQLiteStore._config_from_dict({"name": "Legacy project"})

    assert config.country_code == "USA"
    assert config.system_type == "Direct system"
    assert config.author_name == ""
    assert config.notes == ""
    assert config.street_address == ""
    assert config.city == ""
    assert config.state_or_province == ""
    assert config.postal_code == ""
    assert config.acis_precipitation_field == "TOTAL_PRECIPITATION"
    assert config.graph_auto_step_count == 20
    assert config.system_parameters.pump_capacity_gallons_per_hour == 0.0
    assert config.system_parameters.filtration_pump_capacity_gallons_per_hour == 1200.0
    assert config.system_parameters.filter_recovery_percent == 100.0
    assert config.system_parameters.booster_refill_level_percent == 50.0
    assert config.system_parameters.booster_minimum_operating_volume_percent == 0.0
    assert config.system_parameters.municipal_backup_enabled is True
    assert config.financial_parameters.currency == "USD"
    assert config.financial_parameters.tariff_billing_unit == "per 1,000 gal"
    assert config.financial_parameters.analysis_period_years == 20
    assert config.financial_parameters.discount_rate_percent == 5.0
    assert config.financial_parameters.equipment_replacement_interval_years == 0
    assert config.optimization_parameters.minimum_reliability_percent == 80.0
    assert config.optimization_parameters.electricity_rate_per_kwh == 0.15
    assert config.tank_parameters.minimum_operating_volume_percent == 0.0
    assert config.first_flush_antecedent_dry_days == 1.0
    assert config.first_flush_antecedent_dry_unit == "days"
    assert config.use_synthetic_hourly_rainfall is False
    assert config.unit_system == "English (I-P)"
    assert config.report_sections == {}
    assert config.report_include_system_visualization is False
    assert config.report_include_multitank_charts is False


def test_read_only_store_loads_without_modifying_database(tmp_path: Path) -> None:
    database = tmp_path / "projects.db"
    writable = SQLiteStore(str(database))
    config = default_project_config()
    config.name = "Read only project"
    rainfall = pd.DataFrame(
        {"Date": pd.to_datetime(["2025-01-01"]), "Precipitation": [1.0]}
    )
    curve = pd.DataFrame(
        {"TankSizeGallons": [1000.0], "ReliabilityPercent": [80.0]}
    )
    results = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-01-01"]),
            "ReliabilityPercent": [80.0],
            "DemandGallons": [100.0],
        }
    )
    writable.save_project(config, rainfall, curve, results)
    before = database.read_bytes()

    read_only = SQLiteStore(str(database), read_only=True)
    loaded, _rainfall, _curve, loaded_results = read_only.load_project_with_analysis(
        config.name
    )

    assert loaded.name == config.name
    assert loaded_results["ReliabilityPercent"].tolist() == [80.0]
    assert database.read_bytes() == before
    with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
        read_only.save_project(config, rainfall, curve, results)


def test_read_only_store_rejects_missing_and_incompatible_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        SQLiteStore(str(tmp_path / "missing.db"), read_only=True)

    incompatible = tmp_path / "incompatible.db"
    with sqlite3.connect(incompatible) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")

    with pytest.raises(Exception, match="compatible project database"):
        SQLiteStore(str(incompatible), read_only=True)


def test_read_only_store_rejects_newer_storage_schema(tmp_path: Path) -> None:
    database = tmp_path / "future-read-only.db"
    SQLiteStore(str(database))
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 999")

    with pytest.raises(RuntimeError, match="newer than the supported schema"):
        SQLiteStore(str(database), read_only=True)


def test_report_generation_choices_round_trip_with_project(tmp_path) -> None:
    database = tmp_path / "report-options.db"
    store = SQLiteStore(str(database), backup_dir=tmp_path / "backups")
    config = default_project_config()
    config.name = "Report options"
    config.report_sections = {"notes": False, "financial_analysis": True}
    config.report_include_system_visualization = True
    config.report_include_multitank_charts = True

    store.save_project(config)
    loaded, _rainfall = store.load_project(config.name)

    assert loaded.report_sections == config.report_sections
    assert loaded.report_include_system_visualization is True
    assert loaded.report_include_multitank_charts is True


def test_operating_levels_round_trip_with_project(tmp_path) -> None:
    database = tmp_path / "operating-levels.db"
    store = SQLiteStore(str(database), backup_dir=tmp_path / "backups")
    config = default_project_config()
    config.name = "Operating levels"
    config.tank_parameters.minimum_operating_volume_percent = 12.5
    config.system_parameters.booster_minimum_operating_volume_percent = 20.0

    store.save_project(config)
    loaded, _rainfall = store.load_project(config.name)

    assert loaded.tank_parameters.minimum_operating_volume_percent == 12.5
    assert loaded.system_parameters.booster_minimum_operating_volume_percent == 20.0


def test_storage_and_project_schema_versions_are_explicit(tmp_path) -> None:
    database = tmp_path / "versioned.db"
    store = SQLiteStore(str(database), backup_dir=tmp_path / "backups")
    config = default_project_config()
    config.name = "Versioned"
    store.save_project(config)

    assert store.schema_versions() == {
        "storage": STORAGE_SCHEMA_VERSION,
        "project": PROJECT_SCHEMA_VERSION,
    }
    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT config_json FROM projects WHERE name = 'Versioned'"
        ).fetchone()[0]
    assert json.loads(stored)["project_schema_version"] == PROJECT_SCHEMA_VERSION


def test_newer_storage_schema_is_rejected(tmp_path) -> None:
    database = tmp_path / "future.db"
    store = SQLiteStore(str(database), backup_dir=tmp_path / "backups")
    assert store.schema_versions()["storage"] == STORAGE_SCHEMA_VERSION
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 999")

    with pytest.raises(RuntimeError, match="newer than the supported schema"):
        SQLiteStore(str(database), backup_dir=tmp_path / "backups")


def test_newer_project_schema_is_rejected(tmp_path) -> None:
    database = tmp_path / "future-project.db"
    store = SQLiteStore(str(database), backup_dir=tmp_path / "backups")
    config = default_project_config()
    config.name = "Future"
    store.save_project(config)
    with sqlite3.connect(database) as connection:
        payload = json.loads(
            connection.execute(
                "SELECT config_json FROM projects WHERE name = 'Future'"
            ).fetchone()[0]
        )
        payload["project_schema_version"] = 999
        connection.execute(
            "UPDATE projects SET config_json = ? WHERE name = 'Future'",
            (json.dumps(payload),),
        )

    with pytest.raises(RuntimeError, match="Project schema 999"):
        store.load_project("Future")


def test_successful_saves_create_valid_rotating_backups(tmp_path) -> None:
    database = tmp_path / "projects.db"
    backup_dir = tmp_path / "backups"
    store = SQLiteStore(
        str(database), backup_dir=backup_dir, backup_retention=2
    )
    config = default_project_config()
    config.name = "Backed up"

    for index in range(4):
        config.notes = f"revision {index}"
        store.save_project(config)

    backups = store.list_backups()
    assert len(backups) == 2
    assert all(SQLiteStore._database_is_valid(path) for path in backups)
    assert store.last_backup_error is None


def test_corrupt_database_is_automatically_recovered_from_latest_backup(tmp_path) -> None:
    database = tmp_path / "projects.db"
    backup_dir = tmp_path / "backups"
    store = SQLiteStore(str(database), backup_dir=backup_dir)
    config = default_project_config()
    config.name = "Recoverable"
    config.notes = "saved before corruption"
    store.save_project(config)
    assert store.list_backups()

    Path(f"{database}-wal").unlink(missing_ok=True)
    Path(f"{database}-shm").unlink(missing_ok=True)
    database.write_bytes(b"not a sqlite database")
    recovered = SQLiteStore(str(database), backup_dir=backup_dir)
    loaded, _rainfall = recovered.load_project("Recoverable")

    assert loaded.notes == "saved before corruption"
    assert recovered.recovery_notice is not None
    assert "Recovered projects.db" in recovered.recovery_notice
    assert any(backup_dir.glob("projects-*-corrupt.db"))
    assert all(not path.name.endswith("-corrupt.db") for path in recovered.list_backups())


def test_legacy_reserve_target_migrates_to_zero_minimum_operating_level() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Legacy reserve project",
            "tank_parameters": {
                "initial_fill_percent": 40.0,
                "reliable_fill_percent": 25.0,
            },
        }
    )

    assert config.tank_parameters.initial_fill_percent == 40.0
    assert config.tank_parameters.minimum_operating_volume_percent == 0.0


def test_system_component_parameters_are_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Constrained system",
            "system_parameters": {
                "pump_capacity_gallons_per_hour": 25.0,
                "filtration_pump_capacity_gallons_per_hour": 900.0,
                "filter_recovery_percent": 92.0,
                "booster_tank_size_gallons": 250.0,
                "booster_initial_fill_percent": 40.0,
                "booster_refill_level_percent": 35.0,
                "municipal_backup_enabled": False,
            },
        }
    )

    assert config.system_parameters.pump_capacity_gallons_per_hour == 25.0
    assert config.system_parameters.filtration_pump_capacity_gallons_per_hour == 900.0
    assert config.system_parameters.filter_recovery_percent == 92.0
    assert config.system_parameters.booster_tank_size_gallons == 250.0
    assert config.system_parameters.booster_initial_fill_percent == 40.0
    assert config.system_parameters.booster_refill_level_percent == 35.0
    assert config.system_parameters.booster_minimum_operating_volume_percent == 0.0
    assert config.system_parameters.municipal_backup_enabled is False


def test_legacy_transfer_flow_is_mapped_to_supported_filtration_system_size() -> None:
    config = SQLiteStore._config_from_dict({
        "name": "Legacy nonstandard transfer flow",
        "system_parameters": {"filtration_pump_capacity_gallons_per_hour": 1900.0},
    })

    assert config.system_parameters.filtration_system_flow_gpm == 30
    assert config.system_parameters.filtration_pump_capacity_gallons_per_hour == 1800.0


def test_filtration_parallel_count_and_infinite_flow_round_trip() -> None:
    config = SQLiteStore._config_from_dict({
        "name": "Unlimited parallel filtration",
        "system_parameters": {
            "filtration_system_flow_gpm": 0,
            "filtration_system_count": 3,
        },
    })

    assert config.system_parameters.filtration_system_flow_gpm == 0
    assert config.system_parameters.filtration_system_count == 3
    assert config.system_parameters.transfer_pump_capacity_gallons_per_hour == 0.0


def test_first_flush_settings_are_loaded_and_legacy_surfaces_default_to_zero() -> None:
    config = SQLiteStore._config_from_dict({
        "name": "First flush project",
        "first_flush_antecedent_dry_days": 4.5,
        "first_flush_antecedent_dry_unit": "hours",
        "surfaces": [
            {"name": "New roof", "area": 1000.0, "runoff_coefficient": 0.9,
             "first_flush_depth_inches": 0.08},
            {"name": "Legacy roof", "area": 500.0, "runoff_coefficient": 0.8},
        ],
    })

    assert config.first_flush_antecedent_dry_days == 4.5
    assert config.first_flush_antecedent_dry_unit == "hours"
    assert config.surfaces[0].first_flush_depth_inches == pytest.approx(0.08)
    assert config.surfaces[1].first_flush_depth_inches == pytest.approx(0.0)


def test_first_flush_guidance_settings_are_loaded_and_normalized() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Guided first flush",
            "first_flush_sizing_method": "guided",
            "first_flush_design_preset": "enhanced_nonpotable",
        }
    )

    assert config.first_flush_sizing_method == "guided"
    assert config.first_flush_design_preset == "enhanced_nonpotable"


def test_legacy_project_keeps_manual_first_flush_sizing() -> None:
    config = SQLiteStore._config_from_dict({"name": "Legacy first flush"})

    assert config.first_flush_sizing_method == "manual"
    assert config.first_flush_design_preset == "code_minimum"


def test_financial_parameters_are_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Financial project",
            "financial_parameters": {
                "currency": "CAD",
                "water_rate": 4.5,
                "sewer_rate": 7.25,
                "tariff_billing_unit": "per m³",
                "sewer_eligible_percent": 40.0,
                "installed_cost": 12000.0,
                "incentives": 1000.0,
                "fixed_annual_maintenance": 125.0,
                "annual_maintenance_percent": 1.5,
                "analysis_period_years": 25,
                "discount_rate_percent": 4.25,
                "utility_rate_escalation_percent": 3.0,
                "maintenance_escalation_percent": 2.0,
                "electricity_escalation_percent": 1.5,
                "pump_power_kw": 0.75,
                "pump_flow_rate_gallons_per_hour": 600.0,
                "equipment_replacement_cost": 2400.0,
                "equipment_replacement_interval_years": 10,
                "equipment_replacement_escalation_percent": 2.5,
            },
        }
    )

    assert config.financial_parameters.currency == "CAD"
    assert config.financial_parameters.tariff_billing_unit == "per m³"
    assert config.financial_parameters.installed_cost == 12000.0
    assert config.financial_parameters.analysis_period_years == 25
    assert config.financial_parameters.discount_rate_percent == 4.25
    assert config.financial_parameters.pump_power_kw == 0.75
    assert config.financial_parameters.equipment_replacement_cost == 2400.0
    assert config.financial_parameters.equipment_replacement_interval_years == 10


def test_optimization_parameters_are_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Optimization project",
            "optimization_parameters": {
                "minimum_reliability_percent": 92.5,
                "electricity_rate_per_kwh": 0.24,
                "objective": "Net annual savings",
                "maximum_annual_municipal_makeup_gallons": 5000.0,
                "maximum_installed_cost": 18000.0,
                "require_positive_net_savings": True,
                "catalog": [{"category": "Primary tank", "name": "T1", "capacity": 1000.0, "cost": 500.0, "power_kw": 0.0}],
            },
        }
    )

    assert config.optimization_parameters.minimum_reliability_percent == 92.5
    assert config.optimization_parameters.electricity_rate_per_kwh == 0.24
    assert config.optimization_parameters.objective == "Net annual savings"
    assert config.optimization_parameters.maximum_annual_municipal_makeup_gallons == 5000.0
    assert config.optimization_parameters.maximum_installed_cost == 18000.0
    assert config.optimization_parameters.require_positive_net_savings is True
    assert config.optimization_parameters.catalog[0]["name"] == "T1"


def test_demand_objects_are_loaded_as_model_objects() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Object demand",
            "demand": {
                "hourly_schedule_library": {
                    "Weekdays": {"mon": [1.0] + [0.0] * 23}
                },
                "demand_objects": [
                    {
                        "name": "Landscape irrigation",
                        "object_type": "Irrigation system",
                        "daily_demand_gallons": 250.0,
                        "schedule_name": "Weekdays",
                    }
                ]
            },
        }
    )

    assert config.demand.demand_objects[0].name == "Landscape irrigation"
    assert config.demand.demand_objects[0].instantaneous_demand_gallons_per_minute == 250.0 / 60.0
    assert config.demand.demand_objects[0].sewer_eligible is False


def test_legacy_aggregate_demands_migrate_and_assign_to_end_uses() -> None:
    config = SQLiteStore._config_from_dict({
        "name": "Legacy demand project",
        "demand": {
            "simple_daily_demand_gallons": 40.0,
            "daily_demand_days_per_week": 5,
            "spray_irrigation": {"jan": 310.0},
        },
        "system_layout": [
            {"id": "uses", "component_type": "end_uses"},
        ],
    })

    assert config.demand.legacy_inputs_migrated
    assert config.demand.simple_daily_demand_gallons == 0.0
    assert [item.name for item in config.demand.demand_objects] == [
        "Simple recurring demand", "Spray irrigation",
    ]
    assert config.system_layout[0]["demand_object_indices"] == [0, 1]
    assert all(
        item.uses_legacy_sewer_eligibility
        for item in config.demand.demand_objects
    )


def test_instantaneous_demand_object_flow_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Object flow",
            "demand": {
                "demand_objects": [
                    {
                        "name": "Cooling tower",
                        "object_type": "Cooling tower",
                        "instantaneous_demand_gallons_per_minute": 12.5,
                        "schedule_name": "Always on",
                    }
                ]
            },
        }
    )

    assert config.demand.demand_objects[0].instantaneous_demand_gallons_per_minute == 12.5


def test_demand_object_operating_weekdays_are_loaded() -> None:
    config = SQLiteStore._config_from_dict({
        "name": "Weekend demand",
        "demand": {
            "demand_objects": [{
                "name": "Weekend irrigation",
                "object_type": "Irrigation system",
                "demand_mode": "recurring_daily",
                "recurring_daily_gallons": 50.0,
                "operating_days_per_week": 2,
                "operating_weekdays": [5, 6],
            }],
        },
    })

    demand_object = config.demand.demand_objects[0]
    assert demand_object.operating_weekdays == [5, 6]
    assert demand_object.operating_days_per_week == 2


def test_legacy_fixture_weekdays_are_migrated_into_a_dedicated_schedule() -> None:
    always_on = {
        day: [1.0] * 24
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    config = SQLiteStore._config_from_dict(
        {
            "name": "Legacy fixture weekdays",
            "demand": {
                "hourly_schedule_library": {"Always on": always_on},
                "demand_objects": [
                    {
                        "name": "Office toilets",
                        "object_type": "Toilet",
                        "schedule_name": "Always on",
                        "demand_mode": "fixture_usage",
                        "fixture_people": 10.0,
                        "fixture_uses_per_person_per_day": 3.0,
                        "fixture_volume_gallons_per_use": 1.28,
                        "operating_weekdays": [0, 1, 2, 3, 4],
                    }
                ],
            },
        },
        project_schema_version=5,
    )

    fixture = config.demand.demand_objects[0]
    assert fixture.schedule_name != "Always on"
    migrated = config.demand.hourly_schedule_library[fixture.schedule_name]
    assert (
        config.demand.hourly_schedule_types[fixture.schedule_name]
        == OCCUPANCY_SCHEDULE_TYPE
    )
    assert migrated["mon"] == [1.0] * 24
    assert migrated["sat"] == [0.0] * 24
    assert fixture.operating_weekdays == [0, 1, 2, 3, 4]


def test_legacy_recurring_and_monthly_modes_migrate_to_occupancy_schedules() -> None:
    fractional = {
        day: [0.0] * 8 + [0.5] * 9 + [0.0] * 7
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    config = SQLiteStore._config_from_dict(
        {
            "name": "Legacy occupational schedules",
            "demand": {
                "legacy_inputs_migrated": True,
                "hourly_schedule_library": {"Fractional": fractional},
                "hourly_schedule_types": {"Fractional": "fractional"},
                "demand_objects": [
                    {
                        "name": "Daily",
                        "schedule_name": "Fractional",
                        "demand_mode": "recurring_daily",
                        "recurring_daily_gallons": 50.0,
                        "operating_weekdays": [0, 2],
                    },
                    {
                        "name": "Monthly",
                        "schedule_name": "Fractional",
                        "demand_mode": "monthly_volume",
                        "monthly_demand_gallons": {"jan": 310.0},
                    },
                    {
                        "name": "Monthly without schedule",
                        "schedule_name": "",
                        "demand_mode": "monthly_volume",
                        "monthly_demand_gallons": {"jan": 310.0},
                    },
                ],
            },
        },
        project_schema_version=7,
    )

    daily, monthly, monthly_without_schedule = config.demand.demand_objects
    assert daily.schedule_name != monthly.schedule_name
    assert daily.operating_weekdays == [0, 2]
    assert daily.schedule_name != "Fractional"
    assert (
        config.demand.hourly_schedule_types[daily.schedule_name]
        == OCCUPANCY_SCHEDULE_TYPE
    )
    assert config.demand.hourly_schedule_library[daily.schedule_name]["mon"] == (
        [0.0] * 8 + [1.0] * 9 + [0.0] * 7
    )
    assert config.demand.hourly_schedule_library[daily.schedule_name]["tue"] == [0.0] * 24
    assert monthly_without_schedule.schedule_name == "Always occupied"
    assert (
        config.demand.hourly_schedule_types["Always occupied"]
        == OCCUPANCY_SCHEDULE_TYPE
    )


def test_schedule_type_metadata_round_trips_with_project(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "schedule-types.db"))
    config = default_project_config()
    config.name = "Typed schedules"
    config.demand.hourly_schedule_library["Occupied"] = {
        day: [1.0] * 24
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    config.demand.hourly_schedule_types["Occupied"] = OCCUPANCY_SCHEDULE_TYPE
    config.demand.hourly_schedule_months["Occupied"] = [3, 4, 5]

    store.save_project(config)
    loaded, _rainfall = store.load_project(config.name)

    assert loaded.demand.hourly_schedule_types["Occupied"] == OCCUPANCY_SCHEDULE_TYPE
    assert loaded.demand.hourly_schedule_months["Occupied"] == [3, 4, 5]


def test_legacy_schedule_without_month_metadata_defaults_to_all_months() -> None:
    config = SQLiteStore._config_from_dict({
        "name": "Legacy schedule months",
        "demand": {
            "hourly_schedule_library": {
                "Always": {
                    day: [1.0] * 24
                    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
                }
            }
        },
    })

    assert "Always" not in config.demand.hourly_schedule_months


def test_system_builder_layout_is_loaded() -> None:
    layout = [
        {"id": "primary_tank_1", "component_type": "primary_tank", "name": "Primary tank", "x": 120, "y": 80},
        {
            "id": "booster_tank_1", "component_type": "booster_tank",
            "name": "Buffer tank", "x": 260, "y": 80, "extra_input_node": True,
        },
        {
            "id": "end_uses_1",
            "component_type": "end_uses",
            "name": "End-uses",
            "x": 400,
            "y": 80,
            "demand_object_indices": [0, 2],
        },
    ]

    connections = [
        {"source_component": "rainwater_input_1", "target_component": "primary_tank_1"},
        {
            "source_component": "municipal_backup_1",
            "target_component": "booster_tank_1", "target_port": "in2",
        },
    ]
    config = SQLiteStore._config_from_dict(
        {"name": "Builder", "system_layout": layout, "system_connections": connections}
    )

    assert config.system_layout[:len(layout)] == layout
    assert config.system_layout[-1]["component_type"] == "overflow_pipe"
    assert config.system_connections[:len(connections)] == connections
    assert config.system_connections[-1] == {
        "source_component": "primary_tank_1",
        "source_port": "overflow",
        "target_component": config.system_layout[-1]["id"],
    }


def test_custom_system_template_library_crud(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "templates.db"))
    template = {
        "version": 1,
        "system_type": "Indirect system",
        "system_layout": [{"id": "booster", "component_type": "booster_tank"}],
        "system_connections": [],
    }

    store.save_system_template("My system", template)

    assert store.list_system_templates() == ["My system"]
    assert store.load_system_template("my SYSTEM") == template

    store.rename_system_template("My system", "Office system")
    assert store.list_system_templates() == ["Office system"]

    store.delete_system_template("office SYSTEM")
    assert store.list_system_templates() == []


def test_project_round_trip_preserves_synthetic_hourly_rainfall(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "hourly-rainfall.db"))
    config = default_project_config()
    config.name = "Hourly rainfall"
    config.use_synthetic_hourly_rainfall = True
    daily = pd.DataFrame({
        "Date": pd.date_range("2025-01-01", periods=2, freq="D"),
        "Precipitation": [0.4, 0.0],
    })
    generated = disaggregate_daily_rainfall_hyetos(daily, seed=8)

    store.save_project(config, generated)
    loaded_config, loaded = store.load_project(config.name)

    assert has_hourly_rainfall(loaded)
    assert loaded_config.use_synthetic_hourly_rainfall is True
    assert loaded.loc[:, HOURLY_PRECIPITATION_COLUMNS].to_numpy() == pytest.approx(
        generated.loc[:, HOURLY_PRECIPITATION_COLUMNS].to_numpy()
    )


def test_project_round_trip_preserves_rainfall_provenance(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "rainfall-provenance.db"))
    config = default_project_config()
    config.name = "Rainfall provenance"
    config.rainfall_data_type = "observed"
    config.rainfall_temporal_resolution = "daily"
    config.rainfall_timezone = "America/Toronto"
    config.rainfall_timing_type = "Observed daily totals"
    config.rainfall_retrieved_at = "2026-07-21T12:00:00+02:00"
    config.rainfall_known_missing_dates = ["2024-03-04", "2024-03-05"]

    store.save_project(
        config,
        pd.DataFrame({"Date": [pd.Timestamp("2024-01-01")], "Precipitation": [0.0]}),
    )
    loaded_config, _rainfall = store.load_project(config.name)

    assert loaded_config.rainfall_data_type == "observed"
    assert loaded_config.rainfall_temporal_resolution == "daily"
    assert loaded_config.rainfall_timezone == "America/Toronto"
    assert loaded_config.rainfall_timing_type == "Observed daily totals"
    assert loaded_config.rainfall_retrieved_at == "2026-07-21T12:00:00+02:00"
    assert loaded_config.rainfall_known_missing_dates == ["2024-03-04", "2024-03-05"]


def test_invalid_rainfall_provenance_values_are_safely_normalized() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Legacy provenance",
            "rainfall_data_type": "forecast",
            "rainfall_temporal_resolution": "fortnightly",
        }
    )

    assert config.rainfall_data_type == "unclassified"
    assert config.rainfall_temporal_resolution == "unknown"

def test_custom_system_template_names_are_unique_case_insensitively(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "templates.db"))
    store.save_system_template("Campus", {"system_layout": []})

    with pytest.raises(ValueError, match="already exists"):
        store.save_system_template("CAMPUS", {"system_layout": []})


def test_graph_auto_step_count_is_loaded() -> None:
    config = SQLiteStore._config_from_dict({"name": "Custom steps", "graph_auto_step_count": 32})

    assert config.graph_auto_step_count == 32


def test_design_recommendation_settings_are_loaded_and_clamped() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Recommendations",
            "recommendation_reliability_target_percent": 120.0,
            "recommendation_marginal_gain_threshold": -2.0,
        }
    )

    assert config.recommendation_reliability_target_percent == 100.0
    assert config.recommendation_marginal_gain_threshold == 0.0


def test_legacy_hourly_schedule_is_migrated_to_schedule_library() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Legacy hourly",
            "demand": {
                "hourly_schedule_enabled": True,
                "hourly_weekly_fractions": {"mon": [1.0] + [0.0] * 23},
            },
        }
    )

    assert config.demand.active_hourly_schedule_name == "Typical week demand"
    assert config.demand.hourly_schedule_library["Typical week demand"]["mon"][0] == 1.0


def test_project_country_code_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {"name": "Canadian project", "country_code": "CAN", "canadian_precipitation_field": "TOTAL_RAIN"}
    )

    assert config.country_code == "CAN"
    assert config.canadian_precipitation_field == "TOTAL_RAIN"


def test_project_system_type_is_loaded() -> None:
    config = SQLiteStore._config_from_dict({"name": "Indirect project", "system_type": "Indirect system"})

    assert config.system_type == "Indirect system"


def test_project_author_name_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {"name": "Authored project", "author_name": "Jane Engineer", "notes": "First line\nSecond line"}
    )

    assert config.author_name == "Jane Engineer"
    assert config.notes == "First line\nSecond line"


def test_acis_precipitation_field_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {"name": "US project", "country_code": "USA", "acis_precipitation_field": "TOTAL_RAIN"}
    )

    assert config.acis_precipitation_field == "TOTAL_RAIN"


def test_structured_project_address_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Addressed project",
            "street_address": "1121 Brittain Estates Drive",
            "city": "Kingsport",
            "state_or_province": "Tennessee",
            "postal_code": "37664",
            "latitude": 36.548921,
            "longitude": -82.456789,
        }
    )

    assert config.street_address == "1121 Brittain Estates Drive"
    assert config.city == "Kingsport"
    assert config.state_or_province == "Tennessee"
    assert config.postal_code == "37664"
    assert config.latitude == 36.548921
    assert config.longitude == -82.456789


def test_comparison_tank_sizes_are_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Comparison project",
            "unit_system": "Metric",
            "multitank_comparison_enabled": True,
            "comparison_tank_sizes_gal": [2500, 5000.5, 10000],
            "analysis_unit_system": "Metric",
        }
    )

    assert config.multitank_comparison_enabled is True
    assert config.unit_system == "Metric (SI)"
    assert config.comparison_tank_sizes_gal == [2500.0, 5000.5, 10000.0]
    assert config.analysis_unit_system == "Metric (SI)"


def test_single_field_address_migrates_to_street_address() -> None:
    config = SQLiteStore._config_from_dict(
        {"name": "Earlier address project", "address": "1121 Brittain Estates Drive"}
    )

    assert config.street_address == "1121 Brittain Estates Drive"


def test_analysis_input_signature_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {"name": "Analyzed project", "analysis_input_signature": "signature-from-last-run"}
    )

    assert config.analysis_input_signature == "signature-from-last-run"
