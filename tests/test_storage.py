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


def test_system_builder_layout_is_loaded() -> None:
    layout = [
        {"id": "primary_tank_1", "component_type": "primary_tank", "name": "Primary tank", "x": 120, "y": 80},
        {
            "id": "end_uses_1",
            "component_type": "end_uses",
            "name": "End-uses",
            "x": 400,
            "y": 80,
            "demand_object_indices": [0, 2],
        },
    ]

    connections = [{"source_component": "rainwater_input_1", "target_component": "primary_tank_1"}]
    config = SQLiteStore._config_from_dict(
        {"name": "Builder", "system_layout": layout, "system_connections": connections}
    )

    assert config.system_layout == layout
    assert config.system_connections == connections


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
