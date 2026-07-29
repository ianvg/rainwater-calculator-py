import pytest

from rainwater_app.defaults import default_project_config
from rainwater_app.system_builder_controller import (
    adjacent_animation_date,
    animation_connection_active,
    animation_connection_flow_gallons,
    animation_drag_delta,
    animation_frames_per_hour,
    animation_pipe_flow_label,
    blocks_overlap,
    bounded_animation_seconds,
    bounded_pan,
    bounded_zoom,
    component_ports,
    connection_points,
    connections_after_node_disconnect,
    next_animation_date,
    point_along_connection,
    port_is_output,
    required_canvas_size,
    single_hour_animation_completion,
)


def test_animation_navigation_and_timing_rules_are_bounded() -> None:
    dates = ("2026-01-01", "2026-01-02")

    assert adjacent_animation_date(dates, dates[0], 1) == dates[1]
    assert adjacent_animation_date(dates, dates[0], -1) is None
    assert next_animation_date(dates, dates[1]) is None
    assert bounded_animation_seconds(0.0) == pytest.approx(0.1)
    assert bounded_animation_seconds(100.0) == pytest.approx(60.0)
    assert animation_frames_per_hour(1.0) == 25
    assert single_hour_animation_completion(8, "Loop current hour") == (8, False)
    assert single_hour_animation_completion(23, "Advance") == (23, True)


def test_animation_flow_rules_use_the_matching_component_result() -> None:
    row = {
        "GrossCollectedGallons": 12.0,
        "CollectedGallons": 10.0,
        "OverflowGallons": 2.0,
        "PumpFlowGallons": 8.0,
        "FilterThroughputGallons": 7.0,
        "MainsMakeupGallons": 3.0,
        "DemandGallons": 11.0,
        "SystemUnmetDemandGallons": 1.0,
    }

    assert animation_connection_flow_gallons(
        "rainwater_input", "first_flush_diversion", row
    ) == pytest.approx(12.0)
    assert animation_connection_flow_gallons(
        "primary_tank", "overflow_pipe", row
    ) == pytest.approx(2.0)
    assert animation_connection_flow_gallons(
        "booster_tank", "end_uses", row
    ) == pytest.approx(10.0)
    assert animation_connection_active("filtration_system", "booster_tank", row)


def test_animation_flow_label_respects_project_units() -> None:
    imperial = default_project_config()
    metric = default_project_config()
    metric.unit_system = "Metric (SI)"

    assert animation_pipe_flow_label(60.0, imperial) == "1 GPM"
    assert animation_pipe_flow_label(60.0, metric) == "3.8 LPM"


def test_builder_viewport_and_overlap_rules_are_deterministic() -> None:
    layout = [{"x": 900.0, "y": 520.0, "width": 200.0, "height": 80.0}]

    assert blocks_overlap(100.0, 100.0, 220.0, 100.0)
    assert not blocks_overlap(100.0, 100.0, 232.0, 100.0)
    assert required_canvas_size(layout) == (1032, 576)
    assert required_canvas_size([]) == (760, 420)
    assert bounded_zoom(1.0, 0.1) == pytest.approx(1.1)
    assert bounded_zoom(1.3, 0.1) == pytest.approx(1.3)
    assert bounded_pan(700.0, 420.0, 1.0, 100.0, 100.0) == (0.0, 0.0)


def test_builder_port_and_disconnect_rules_preserve_unrelated_connections() -> None:
    connections = [
        {
            "source_component": "a",
            "source_port": "out",
            "target_component": "b",
            "target_port": "in",
        },
        {
            "source_component": "b",
            "source_port": "out2",
            "target_component": "c",
            "target_port": "in",
        },
    ]

    assert component_ports("rainwater_input") == (False, True)
    assert component_ports("overflow_pipe") == (True, False)
    assert port_is_output("overflow")
    assert connections_after_node_disconnect(connections, "b", "in") == [connections[1]]
    assert connections_after_node_disconnect(connections, "b", "out2") == [connections[0]]


def test_connection_routing_and_animation_position_share_one_geometry_model() -> None:
    points = connection_points(500.0, 180.0, 220.0, 180.0, 420.0)

    assert points[0:2] == (565.0, 180.0)
    assert points[-2:] == (155.0, 180.0)
    assert point_along_connection((0.0, 0.0, 10.0, 0.0, 10.0, 30.0), 0.5) == (
        10.0,
        10.0,
    )
    assert animation_drag_delta(20.0, -10.0, 2.0) == (10.0, -5.0)
