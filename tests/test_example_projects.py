import pytest
from unittest.mock import Mock

from rainwater_app.example_projects import EXAMPLE_PROJECT_LABELS, build_completed_example
from tkinter_app import RainwaterTkApp


@pytest.mark.parametrize("example_id", EXAMPLE_PROJECT_LABELS)
def test_builtin_example_has_inputs_and_completed_simulation(example_id: str) -> None:
    example = build_completed_example(example_id)

    assert example.config.surfaces
    assert example.config.demand.demand_objects
    assert len(example.rainfall) == 1_095
    assert not example.outcome.curve.empty
    assert not example.outcome.selected_tank.empty
    assert "ReliabilityPercent" in example.outcome.selected_tank
    assert example.config.analysis_input_signature
    assert example.config.analysis_unit_system == example.config.unit_system


def test_unknown_builtin_example_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown example project"):
        build_completed_example("missing")


def test_save_on_builtin_example_uses_save_as() -> None:
    app = object.__new__(RainwaterTkApp)
    app.active_example_id = "home_garden"
    app.save_project_as = Mock(return_value=True)
    app._apply_form_to_model = Mock()
    app._save_current_project = Mock()

    assert RainwaterTkApp.save_project(app) is True
    app.save_project_as.assert_called_once_with()
    app._save_current_project.assert_not_called()
