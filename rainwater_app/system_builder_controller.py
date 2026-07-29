"""UI-independent interaction rules for the desktop system builder and animation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from rainwater_app.models import ProjectConfig
from rainwater_app.number_formatting import format_number
from rainwater_app.units import LITERS_PER_GALLON, is_metric


SYSTEM_ANIMATION_FRAME_MS = 40


def adjacent_animation_date(
    values: Sequence[str], current: str, delta: int
) -> str | None:
    if not values:
        return None
    try:
        index = values.index(current)
    except ValueError:
        return values[0]
    target_index = index + (-1 if delta < 0 else 1)
    if 0 <= target_index < len(values):
        return values[target_index]
    return None


def next_animation_date(values: Sequence[str], current: str) -> str | None:
    return adjacent_animation_date(values, current, 1)


def animation_drag_delta(
    screen_dx: float, screen_dy: float, scale: float
) -> tuple[float, float]:
    safe_scale = max(float(scale), 0.001)
    return float(screen_dx) / safe_scale, float(screen_dy) / safe_scale


def bounded_animation_seconds(value: float) -> float:
    return min(max(float(value), 0.1), 60.0)


def animation_frames_per_hour(seconds_per_hour: float) -> int:
    bounded = bounded_animation_seconds(seconds_per_hour)
    return max(round(bounded * 1000.0 / SYSTEM_ANIMATION_FRAME_MS), 1)


def single_hour_animation_completion(hour: int, behavior: str) -> tuple[int, bool]:
    bounded_hour = min(max(int(hour), 0), 23)
    if behavior == "Loop current hour":
        return bounded_hour, False
    return min(bounded_hour + 1, 23), True


def animation_connection_active(
    source_type: str, target_type: str, row: Mapping[str, object]
) -> bool:
    if source_type == "rainwater_input":
        field = (
            "GrossCollectedGallons"
            if target_type == "first_flush_diversion"
            else "CollectedGallons"
        )
        return float(row.get(field, 0.0)) > 1e-9
    if source_type == "first_flush_diversion":
        return float(row.get("CollectedGallons", 0.0)) > 1e-9
    if source_type == "municipal_backup":
        return float(row.get("MainsMakeupGallons", 0.0)) > 1e-9
    if target_type == "overflow_pipe":
        return float(row.get("OverflowGallons", 0.0)) > 1e-9
    if source_type in {"primary_tank", "filtration_pump"}:
        return float(row.get("PumpFlowGallons", 0.0)) > 1e-9
    if source_type == "filtration_system":
        return float(row.get("FilterThroughputGallons", 0.0)) > 1e-9
    if source_type in {"booster_tank", "booster_pump"}:
        supplied = float(row.get("DemandGallons", 0.0)) - float(
            row.get("SystemUnmetDemandGallons", 0.0)
        )
        return supplied > 1e-9
    return False


def animation_connection_flow_gallons(
    source_type: str, target_type: str, row: Mapping[str, object]
) -> float:
    """Return the volume crossing a builder connection during this hour."""
    if target_type == "overflow_pipe":
        return max(float(row.get("OverflowGallons", 0.0)), 0.0)
    if source_type == "rainwater_input":
        field = (
            "GrossCollectedGallons"
            if target_type == "first_flush_diversion"
            else "CollectedGallons"
        )
        return max(float(row.get(field, 0.0)), 0.0)
    if source_type == "first_flush_diversion":
        return max(float(row.get("CollectedGallons", 0.0)), 0.0)
    if source_type == "municipal_backup":
        return max(float(row.get("MainsMakeupGallons", 0.0)), 0.0)
    if source_type in {"primary_tank", "filtration_pump"}:
        return max(float(row.get("PumpFlowGallons", 0.0)), 0.0)
    if source_type == "filtration_system":
        return max(float(row.get("FilterThroughputGallons", 0.0)), 0.0)
    if source_type in {"booster_tank", "booster_pump"}:
        return max(
            float(row.get("DemandGallons", 0.0))
            - float(row.get("SystemUnmetDemandGallons", 0.0)),
            0.0,
        )
    return 0.0


def animation_pipe_flow_label(hourly_gallons: float, config: ProjectConfig) -> str:
    flow = max(float(hourly_gallons), 0.0) / 60.0
    if is_metric(config):
        return f"{format_number(flow * LITERS_PER_GALLON, config, max_decimal_places=1)} LPM"
    return f"{format_number(flow, config, max_decimal_places=1)} GPM"


def animation_rain_active(row: Mapping[str, object]) -> bool:
    """Return whether collected rainwater enters the configured system this hour."""
    return float(row.get("CollectedGallons", 0.0)) > 1e-9


def blocks_overlap(
    first_x: float, first_y: float, second_x: float, second_y: float
) -> bool:
    """Treat system blocks as solid rectangles with a small visual gap."""
    return rectangles_overlap(
        first_x, first_y, 124.0, 60.0, second_x, second_y, 124.0, 60.0
    )


def rectangles_overlap(
    first_x: float,
    first_y: float,
    first_width: float,
    first_height: float,
    second_x: float,
    second_y: float,
    second_width: float,
    second_height: float,
) -> bool:
    return (
        abs(first_x - second_x) < (first_width + second_width) / 2.0 + 8.0
        and abs(first_y - second_y) < (first_height + second_height) / 2.0 + 8.0
    )


def required_canvas_size(
    layout: Sequence[Mapping[str, object]],
    minimum_width: float = 760.0,
    minimum_height: float = 420.0,
) -> tuple[int, int]:
    """Return a canvas size that contains every system object and its ports."""
    right_edge = float(minimum_width)
    bottom_edge = float(minimum_height)
    for item in layout:
        try:
            x = float(item.get("x", 0.0))
            y = float(item.get("y", 0.0))
            width = max(float(item.get("width", 124.0)), 80.0)
            height = max(float(item.get("height", 60.0)), 44.0)
        except (TypeError, ValueError):
            continue
        right_edge = max(right_edge, x + width / 2.0 + 32.0)
        bottom_edge = max(bottom_edge, y + height / 2.0 + 16.0)
    return math.ceil(right_edge), math.ceil(bottom_edge)


def bounded_zoom(current: float, delta: float) -> float:
    current_steps = round(float(current) * 10)
    delta_steps = 1 if delta > 0 else -1
    return min(max(current_steps + delta_steps, 7), 13) / 10.0


def bounded_pan(
    canvas_width: float,
    canvas_height: float,
    zoom: float,
    pan_x: float,
    pan_y: float,
) -> tuple[float, float]:
    zoom = min(max(float(zoom), 0.7), 1.3)
    world_width = float(canvas_width) / 0.7
    world_height = float(canvas_height) / 0.7
    minimum_x = min(float(canvas_width) / zoom - world_width, 0.0)
    minimum_y = min(float(canvas_height) / zoom - world_height, 0.0)
    return (
        min(max(float(pan_x), minimum_x), 0.0),
        min(max(float(pan_y), minimum_y), 0.0),
    )


def float_range(start: float, stop: float, step: float) -> list[float]:
    values: list[float] = []
    value = start
    while value <= stop + 0.001:
        values.append(value)
        value += step
    return values


def component_ports(component_type: str) -> tuple[bool, bool]:
    has_inlet = component_type not in {"rainwater_input", "municipal_backup"}
    has_outlet = component_type not in {"end_uses", "overflow_pipe"}
    return has_inlet, has_outlet


def port_is_output(direction: str) -> bool:
    return direction.startswith("out") or direction == "overflow"


def connections_after_node_disconnect(
    connections: list[dict[str, str]], component_id: str, direction: str | None
) -> list[dict[str, str]]:
    if direction in {"in", "in2"}:
        return [
            item
            for item in connections
            if item.get("target_component") != component_id
            or item.get("target_port", "in") != direction
        ]
    if direction in {"out", "out2", "overflow"}:
        return [
            item
            for item in connections
            if item.get("source_component") != component_id
            or item.get("source_port", "out") != direction
        ]
    return [
        item
        for item in connections
        if item.get("source_component") != component_id
        and item.get("target_component") != component_id
    ]


def connection_points(
    source_x: float,
    source_y: float,
    target_x: float,
    target_y: float,
    canvas_height: float,
    source_width: float = 124.0,
    target_width: float = 124.0,
    source_height: float = 60.0,
    target_height: float = 60.0,
) -> tuple[float, ...]:
    """Route a connection to the target's left port without crossing either object."""
    start_x = source_x + source_width / 2.0 + 3.0
    end_x = target_x - target_width / 2.0 - 3.0
    if target_x > source_x:
        if abs(target_y - source_y) < 0.001:
            return start_x, source_y, end_x, target_y
        midpoint = (start_x + end_x) / 2.0
        return start_x, source_y, midpoint, source_y, midpoint, target_y, end_x, target_y

    source_rail_x = start_x + 24.0
    target_rail_x = end_x - 24.0
    if abs(target_y - source_y) >= (source_height + target_height) / 2.0 + 24.0:
        corridor_y = (source_y + target_y) / 2.0
    else:
        corridor_offset = max(source_height, target_height) / 2.0 + 22.0
        upper_corridor = min(source_y, target_y) - corridor_offset
        lower_corridor = max(source_y, target_y) + corridor_offset
        if upper_corridor >= 10.0:
            corridor_y = upper_corridor
        elif lower_corridor <= max(canvas_height - 10.0, 10.0):
            corridor_y = lower_corridor
        else:
            corridor_y = upper_corridor
    return (
        start_x,
        source_y,
        source_rail_x,
        source_y,
        source_rail_x,
        corridor_y,
        target_rail_x,
        corridor_y,
        target_rail_x,
        target_y,
        end_x,
        target_y,
    )


def point_along_connection(
    points: tuple[float, ...], fraction: float
) -> tuple[float, float]:
    """Return a distance-weighted point along a routed connection polyline."""
    pairs = list(zip(points[0::2], points[1::2]))
    if not pairs:
        return 0.0, 0.0
    if len(pairs) == 1:
        return pairs[0]
    segments = [
        math.hypot(end[0] - start[0], end[1] - start[1])
        for start, end in zip(pairs, pairs[1:])
    ]
    total_length = sum(segments)
    if total_length <= 0.0:
        return pairs[0]
    remaining = min(max(float(fraction), 0.0), 1.0) * total_length
    for (start, end), length in zip(zip(pairs, pairs[1:]), segments):
        if remaining <= length:
            progress = remaining / length if length > 0.0 else 0.0
            return (
                start[0] + (end[0] - start[0]) * progress,
                start[1] + (end[1] - start[1]) * progress,
            )
        remaining -= length
    return pairs[-1]
