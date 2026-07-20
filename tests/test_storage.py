import pytest
import pandas as pd

from rainwater_app.defaults import default_project_config
from rainwater_app.rainfall import (
    HOURLY_PRECIPITATION_COLUMNS,
    disaggregate_daily_rainfall_hyetos,
    has_hourly_rainfall,
)
from rainwater_app.storage import SQLiteStore


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
    assert config.system_parameters.municipal_backup_enabled is True
    assert config.financial_parameters.currency == "USD"
    assert config.financial_parameters.tariff_billing_unit == "per 1,000 gal"
    assert config.financial_parameters.analysis_period_years == 20
    assert config.optimization_parameters.minimum_reliability_percent == 80.0
    assert config.optimization_parameters.electricity_rate_per_kwh == 0.15
    assert config.tank_parameters.minimum_operating_volume_percent == 0.0
    assert config.first_flush_antecedent_dry_days == 1.0
    assert config.first_flush_antecedent_dry_unit == "days"
    assert config.use_synthetic_hourly_rainfall is False


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
    assert config.system_parameters.municipal_backup_enabled is False


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
            },
        }
    )

    assert config.financial_parameters.currency == "CAD"
    assert config.financial_parameters.tariff_billing_unit == "per m³"
    assert config.financial_parameters.installed_cost == 12000.0
    assert config.financial_parameters.analysis_period_years == 25


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

def test_custom_system_template_names_are_unique_case_insensitively(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "templates.db"))
    store.save_system_template("Campus", {"system_layout": []})

    with pytest.raises(ValueError, match="already exists"):
        store.save_system_template("CAMPUS", {"system_layout": []})


def test_graph_auto_step_count_is_loaded() -> None:
    config = SQLiteStore._config_from_dict({"name": "Custom steps", "graph_auto_step_count": 32})

    assert config.graph_auto_step_count == 32


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
            "multitank_comparison_enabled": True,
            "comparison_tank_sizes_gal": [2500, 5000.5, 10000],
            "analysis_unit_system": "Metric",
        }
    )

    assert config.multitank_comparison_enabled is True
    assert config.comparison_tank_sizes_gal == [2500.0, 5000.5, 10000.0]
    assert config.analysis_unit_system == "Metric"


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
