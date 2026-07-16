import pytest

from rainwater_app.system_model import Connection, build_custom_system, build_system_template


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


def _custom_layout(*types: str) -> list[dict[str, object]]:
    return [
        {"id": f"{component_type}_1", "component_type": component_type, "name": component_type}
        for component_type in types
    ]


def _connections(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [
        {"source_component": f"{source}_1", "target_component": f"{target}_1"}
        for source, target in pairs
    ]


def test_custom_system_accepts_direct_service_and_overflow_paths() -> None:
    layout = _custom_layout("rainwater_input", "primary_tank", "end_uses", "overflow_discharge")
    connections = _connections(
        ("rainwater_input", "primary_tank"),
        ("primary_tank", "end_uses"),
        ("primary_tank", "overflow_discharge"),
    )

    system = build_custom_system(layout, connections)

    assert system.system_type == "Custom system"
    assert system.components["__metadata__"].properties["service_path"] == "primary_tank,end_uses"


def test_custom_system_rejects_a_cycle_and_missing_overflow_path() -> None:
    layout = _custom_layout("rainwater_input", "primary_tank", "booster_pump", "end_uses", "overflow_discharge")
    connections = _connections(
        ("rainwater_input", "primary_tank"),
        ("primary_tank", "booster_pump"),
        ("booster_pump", "primary_tank"),
        ("booster_pump", "end_uses"),
    )

    with pytest.raises(ValueError, match="cycle"):
        build_custom_system(layout, connections)
