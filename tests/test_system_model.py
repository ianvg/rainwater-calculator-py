from rainwater_app.system_model import (
    Connection, build_system_template, compile_builder_system, validate_builder_system,
)


def test_direct_system_template_is_valid() -> None:
    system = build_system_template("Direct system")

    assert system.validate() == []
    assert system.components["distribution_pump"].component_type == "pump"
    assert "filtration" not in system.components


def test_indirect_system_template_contains_treatment_path() -> None:
    system = build_system_template("Indirect system")

    assert system.validate() == []
    assert system.components["filtration"].component_type == "filter"
    assert system.components["booster"].component_type == "booster_tank"
    assert system.components["booster_pump"].component_type == "pump"
    assert Connection("mains", "out", "booster", "in") in system.connections
    assert Connection("booster_pump", "out", "end_uses", "in") in system.connections


def test_system_validation_rejects_invalid_flow_direction() -> None:
    system = build_system_template("Direct system")
    system.connections.append(Connection("primary", "in", "end_uses", "in"))

    assert any("invalid flow direction" in error for error in system.validate())


def test_builder_graph_compiles_indirect_hydraulic_capabilities() -> None:
    component_types = [
        "rainwater_input", "primary_tank", "filtration_pump", "filtration_system",
        "booster_tank", "booster_pump", "end_uses", "municipal_backup",
    ]
    layout = [
        {"id": f"c{index}", "component_type": component_type}
        for index, component_type in enumerate(component_types)
    ]
    connections = [
        {"source_component": "c0", "target_component": "c1"},
        {"source_component": "c1", "target_component": "c2"},
        {"source_component": "c2", "target_component": "c3"},
        {"source_component": "c3", "target_component": "c4"},
        {"source_component": "c4", "target_component": "c5"},
        {"source_component": "c5", "target_component": "c6"},
        {"source_component": "c7", "target_component": "c4"},
    ]

    compiled = compile_builder_system("Direct system", layout, connections)

    assert compiled.uses_builder_graph
    assert compiled.rain_reaches_primary
    assert compiled.primary_reaches_end_uses
    assert compiled.filtration_path
    assert compiled.booster_storage_path
    assert compiled.municipal_reaches_booster
    assert compiled.display_type == "Custom indirect system"


def test_builder_graph_does_not_invent_missing_connections() -> None:
    compiled = compile_builder_system(
        "Indirect system",
        [
            {"id": "rain", "component_type": "rainwater_input"},
            {"id": "tank", "component_type": "primary_tank"},
            {"id": "uses", "component_type": "end_uses"},
        ],
        [],
    )

    assert not compiled.rain_reaches_primary
    assert not compiled.primary_reaches_end_uses


def test_builder_graph_accepts_first_flush_diversion_sink() -> None:
    compiled = compile_builder_system(
        "Direct system",
        [
            {"id": "tank", "component_type": "primary_tank"},
            {"id": "flush", "component_type": "first_flush_diversion"},
        ],
        [{
            "source_component": "tank", "source_port": "out2",
            "target_component": "flush",
        }],
    )

    assert compiled.uses_builder_graph
    assert not compiled.primary_reaches_end_uses


def test_builder_validation_reports_missing_required_flow_paths() -> None:
    warnings = validate_builder_system(
        [
            {"id": "rain", "component_type": "rainwater_input"},
            {"id": "tank", "component_type": "primary_tank"},
            {"id": "uses", "component_type": "end_uses"},
        ],
        [],
    )

    assert "Connect rainwater input to the primary tank." in warnings
    assert "Connect the primary tank to end-uses through a valid supply path." in warnings


def test_builder_validation_accepts_direct_template_layout() -> None:
    layout = [
        {"id": "rain", "component_type": "rainwater_input"},
        {"id": "tank", "component_type": "primary_tank"},
        {"id": "pump", "component_type": "booster_pump"},
        {"id": "uses", "component_type": "end_uses"},
        {"id": "mains", "component_type": "municipal_backup"},
    ]
    connections = [
        {"source_component": "rain", "target_component": "tank"},
        {"source_component": "tank", "target_component": "pump"},
        {"source_component": "pump", "target_component": "uses"},
        {"source_component": "mains", "target_component": "uses"},
    ]

    assert validate_builder_system(
        layout, connections, municipal_backup_enabled=True
    ) == []


def test_builder_validation_requires_a_valid_demand_assignment_for_each_end_use() -> None:
    layout = [
        {"id": "uses-1", "component_type": "end_uses", "name": "Building uses"},
        {
            "id": "uses-2", "component_type": "end_uses", "name": "Irrigation uses",
            "demand_object_indices": [4, "invalid"],
        },
        {
            "id": "uses-3", "component_type": "end_uses", "name": "Washdown uses",
            "demand_object_indices": [1],
        },
    ]

    warnings = validate_builder_system(
        layout, [], demand_object_count=2
    )

    assert "Assign at least one demand object to Building uses." in warnings
    assert "Assign at least one demand object to Irrigation uses." in warnings
    assert "Assign at least one demand object to Washdown uses." not in warnings
