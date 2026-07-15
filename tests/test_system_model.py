from rainwater_app.system_model import Connection, build_system_template


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
