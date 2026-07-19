from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class Port:
    name: str
    direction: str
    medium: str = "water"


@dataclass
class SystemComponent:
    id: str
    component_type: str
    name: str
    ports: dict[str, Port]
    properties: dict[str, float | str | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class Connection:
    source_component: str
    source_port: str
    target_component: str
    target_port: str


@dataclass
class RWHSystem:
    system_type: str
    components: dict[str, SystemComponent]
    connections: list[Connection]

    def validate(self) -> list[str]:
        errors: list[str] = []
        for connection in self.connections:
            source = self.components.get(connection.source_component)
            target = self.components.get(connection.target_component)
            if source is None or target is None:
                errors.append("Connection references a missing component.")
                continue
            source_port = source.ports.get(connection.source_port)
            target_port = target.ports.get(connection.target_port)
            if source_port is None or target_port is None:
                errors.append(f"Connection {source.id} -> {target.id} references a missing port.")
                continue
            if source_port.direction != "out" or target_port.direction != "in":
                errors.append(f"Connection {source.id} -> {target.id} has an invalid flow direction.")
            if source_port.medium != target_port.medium:
                errors.append(f"Connection {source.id} -> {target.id} connects incompatible media.")

        required_types = {"collection", "primary_tank", "end_uses", "overflow"}
        available_types = {component.component_type for component in self.components.values()}
        for missing_type in sorted(required_types - available_types):
            errors.append(f"System is missing required component type: {missing_type}.")
        if not self._is_reachable("collection", "primary_tank"):
            errors.append("Collection is not connected to the primary tank.")
        if not self._is_reachable("primary_tank", "end_uses"):
            errors.append("The primary tank cannot supply the end uses.")
        if not self._is_reachable("primary_tank", "overflow"):
            errors.append("The primary tank has no overflow discharge path.")
        return errors

    def _is_reachable(self, source_type: str, target_type: str) -> bool:
        source_ids = {
            component.id for component in self.components.values() if component.component_type == source_type
        }
        target_ids = {
            component.id for component in self.components.values() if component.component_type == target_type
        }
        adjacency: dict[str, list[str]] = {}
        for connection in self.connections:
            adjacency.setdefault(connection.source_component, []).append(connection.target_component)
        pending = list(source_ids)
        visited: set[str] = set()
        while pending:
            component_id = pending.pop()
            if component_id in target_ids:
                return True
            if component_id in visited:
                continue
            visited.add(component_id)
            pending.extend(adjacency.get(component_id, []))
        return False


BUILDER_COMPONENT_PORTS: dict[str, tuple[bool, bool]] = {
    "rainwater_input": (False, True),
    "primary_tank": (True, True),
    "filtration_pump": (True, True),
    "filtration_system": (True, True),
    "booster_tank": (True, True),
    "booster_pump": (True, True),
    "municipal_backup": (False, True),
    "end_uses": (True, False),
    "first_flush_diversion": (True, False),
}


@dataclass(frozen=True)
class ExecutableSystem:
    """The hydraulic capabilities exposed by a saved builder graph.

    The hourly solver remains a mass-balance solver, while this compiled graph
    decides which sources, stores and treatment devices are actually connected.
    """

    uses_builder_graph: bool
    rain_reaches_primary: bool
    primary_reaches_end_uses: bool
    municipal_reaches_end_uses: bool
    municipal_reaches_booster: bool
    filtration_path: bool
    booster_storage_path: bool
    distribution_pump_path: bool
    display_type: str


def compile_builder_system(
    system_type: str,
    layout: Iterable[dict[str, object]],
    connections: Iterable[dict[str, str]],
) -> ExecutableSystem:
    """Compile the saved canvas into capabilities consumed by the hourly engine.

    Empty layouts are legacy projects and retain the selected template. Invalid
    or disconnected custom graphs are safe: they simply expose no flow along the
    missing path instead of silently simulating a different template.
    """
    items = [dict(item) for item in layout]
    if not items:
        indirect = system_type == "Indirect system"
        return ExecutableSystem(
            uses_builder_graph=False,
            rain_reaches_primary=True,
            primary_reaches_end_uses=True,
            municipal_reaches_end_uses=not indirect,
            municipal_reaches_booster=indirect,
            filtration_path=indirect,
            booster_storage_path=indirect,
            distribution_pump_path=not indirect,
            display_type="Indirect system" if indirect else "Direct system",
        )

    types = {
        str(item.get("id", "")): str(item.get("component_type", ""))
        for item in items
        if str(item.get("id", ""))
    }
    adjacency: dict[str, set[str]] = {component_id: set() for component_id in types}
    for connection in connections:
        source = str(connection.get("source_component", ""))
        target = str(connection.get("target_component", ""))
        source_ports = BUILDER_COMPONENT_PORTS.get(types.get(source, ""))
        target_ports = BUILDER_COMPONENT_PORTS.get(types.get(target, ""))
        if source_ports and target_ports and source_ports[1] and target_ports[0]:
            adjacency[source].add(target)

    def paths(source_type: str, target_type: str) -> list[tuple[str, ...]]:
        sources = [item_id for item_id, item_type in types.items() if item_type == source_type]
        targets = {item_id for item_id, item_type in types.items() if item_type == target_type}
        found: list[tuple[str, ...]] = []
        pending = [(source, (source,)) for source in sources]
        while pending:
            current, path = pending.pop()
            if current in targets:
                found.append(path)
                continue
            for successor in adjacency.get(current, set()):
                if successor not in path:
                    pending.append((successor, path + (successor,)))
        return found

    rain_paths = paths("rainwater_input", "primary_tank")
    supply_paths = paths("primary_tank", "end_uses")
    mains_end_paths = paths("municipal_backup", "end_uses")
    mains_booster_paths = paths("municipal_backup", "booster_tank")
    supply_types = [{types[item_id] for item_id in path} for path in supply_paths]
    filtration_path = any(
        "filtration_pump" in path_types and "filtration_system" in path_types
        for path_types in supply_types
    )
    booster_path = any("booster_tank" in path_types for path_types in supply_types)
    direct_pump_path = any(
        "booster_pump" in path_types and "booster_tank" not in path_types
        for path_types in supply_types
    )
    indirect = filtration_path or booster_path
    return ExecutableSystem(
        uses_builder_graph=True,
        rain_reaches_primary=bool(rain_paths),
        primary_reaches_end_uses=bool(supply_paths),
        municipal_reaches_end_uses=bool(mains_end_paths),
        municipal_reaches_booster=bool(mains_booster_paths),
        filtration_path=filtration_path,
        booster_storage_path=booster_path,
        distribution_pump_path=direct_pump_path,
        display_type="Custom indirect system" if indirect else "Custom direct system",
    )


def validate_builder_system(
    layout: Iterable[dict[str, object]],
    connections: Iterable[dict[str, str]],
    *,
    municipal_backup_enabled: bool = False,
    demand_object_count: int | None = None,
) -> list[str]:
    """Return actionable warnings for a saved builder graph."""
    items = [dict(item) for item in layout]
    if not items:
        return []  # Legacy projects use a known-valid built-in template.
    warnings: list[str] = []
    ids = [str(item.get("id", "")) for item in items]
    if len(ids) != len(set(ids)):
        warnings.append("Component IDs must be unique.")
    types = {
        str(item.get("id", "")): str(item.get("component_type", ""))
        for item in items if str(item.get("id", ""))
    }
    unknown = sorted({value for value in types.values() if value not in BUILDER_COMPONENT_PORTS})
    if unknown:
        warnings.append("Unknown component type(s): " + ", ".join(unknown) + ".")
    adjacency: dict[str, list[str]] = {item_id: [] for item_id in types}
    incoming: dict[str, int] = {item_id: 0 for item_id in types}
    valid_connections: list[tuple[str, str, str, str]] = []
    for connection in connections:
        source = str(connection.get("source_component", ""))
        target = str(connection.get("target_component", ""))
        source_port = str(connection.get("source_port", "out"))
        target_port = str(connection.get("target_port", "in"))
        if source not in types or target not in types:
            warnings.append("A connection references a missing component.")
            continue
        if source == target:
            warnings.append(f"{source} cannot connect to itself.")
            continue
        source_spec = BUILDER_COMPONENT_PORTS.get(types[source])
        target_spec = BUILDER_COMPONENT_PORTS.get(types[target])
        if not source_spec or not source_spec[1] or not target_spec or not target_spec[0]:
            warnings.append(f"Invalid flow direction from {source} to {target}.")
            continue
        adjacency[source].append(target)
        incoming[target] += 1
        valid_connections.append((source, target, source_port, target_port))

    def ids_of(component_type: str) -> list[str]:
        return [item_id for item_id, value in types.items() if value == component_type]

    if demand_object_count is not None:
        available_demand_objects = max(int(demand_object_count), 0)
        for item in items:
            if str(item.get("component_type", "")) != "end_uses":
                continue
            assigned = item.get("demand_object_indices", [])
            if not isinstance(assigned, (list, tuple, set)):
                assigned = []
            valid_assignments: set[int] = set()
            for value in assigned:
                try:
                    index = int(value)
                except (TypeError, ValueError):
                    continue
                if 0 <= index < available_demand_objects:
                    valid_assignments.add(index)
            if not valid_assignments:
                name = str(item.get("name") or item.get("id") or "End uses")
                warnings.append(
                    f"Assign at least one demand object to {name}."
                )

    def reachable(source_types: set[str], target_types: set[str]) -> bool:
        pending = [item_id for item_id, value in types.items() if value in source_types]
        targets = {item_id for item_id, value in types.items() if value in target_types}
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current in targets:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(adjacency.get(current, []))
        return False

    def can_reach_id(source_ids: Iterable[str], target_id: str) -> bool:
        pending = list(source_ids)
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(adjacency.get(current, []))
        return False

    for component_type, label in (
        ("rainwater_input", "rainwater input"),
        ("primary_tank", "primary tank"),
        ("end_uses", "end-uses"),
    ):
        count = len(ids_of(component_type))
        if count == 0:
            warnings.append(f"Add a {label} component.")
        elif component_type == "primary_tank" and count > 1:
            warnings.append("The current simulation supports exactly one primary tank.")
    if not reachable({"rainwater_input"}, {"primary_tank"}):
        warnings.append("Connect rainwater input to the primary tank.")
    if not reachable({"primary_tank"}, {"end_uses"}):
        warnings.append("Connect the primary tank to end-uses through a valid supply path.")
    if municipal_backup_enabled and not (
        reachable({"municipal_backup"}, {"end_uses"})
        or reachable({"municipal_backup"}, {"booster_tank"})
    ):
        warnings.append("Municipal backup is enabled but has no usable destination.")
    filtration_pumps = ids_of("filtration_pump")
    for filter_id in ids_of("filtration_system"):
        if not can_reach_id(filtration_pumps, filter_id):
            warnings.append(
                f"{filter_id} must be downstream of a filtration pump."
            )
    booster_pumps = ids_of("booster_pump")
    end_use_ids = ids_of("end_uses")
    for booster_id in ids_of("booster_tank"):
        usable_pumps = [pump_id for pump_id in booster_pumps if can_reach_id([booster_id], pump_id)]
        if not any(can_reach_id([pump_id], end_id) for pump_id in usable_pumps for end_id in end_use_ids):
            warnings.append(
                f"{booster_id} must discharge through a booster pump to end-uses."
            )

    visiting: set[str] = set()
    visited: set[str] = set()
    def has_cycle(current: str) -> bool:
        if current in visiting:
            return True
        if current in visited:
            return False
        visiting.add(current)
        if any(has_cycle(successor) for successor in adjacency.get(current, [])):
            return True
        visiting.remove(current)
        visited.add(current)
        return False
    if any(has_cycle(item_id) for item_id in types if item_id not in visited):
        warnings.append("Remove flow loops; the simulation requires an acyclic system.")

    for item_id, component_type in types.items():
        if component_type not in {"rainwater_input", "municipal_backup"} and incoming[item_id] == 0:
            warnings.append(f"{item_id} has no incoming connection.")
        if component_type not in {"end_uses", "first_flush_diversion"} and not adjacency[item_id]:
            warnings.append(f"{item_id} has no outgoing connection.")
    for source, target, source_port, _target_port in valid_connections:
        if source_port == "out2" and types.get(source) == "primary_tank" and types.get(target) != "first_flush_diversion":
            warnings.append("The primary tank's second outlet must connect to first-flush diversion.")
        if types.get(target) == "first_flush_diversion" and not (
            types.get(source) == "primary_tank" and source_port == "out2"
        ):
            warnings.append("First-flush diversion must connect from the primary tank's second outlet.")
    by_id = {str(item.get("id", "")): item for item in items}
    for item_id, item in by_id.items():
        if item.get("component_type") == "primary_tank" and item.get("extra_output_node"):
            if not any(source == item_id and source_port == "out2" for source, _target, source_port, _port in valid_connections):
                warnings.append("Connect or remove the primary tank's second outlet.")
        if item.get("component_type") == "booster_tank" and item.get("extra_input_node"):
            if not any(target == item_id and target_port == "in2" for _source, target, _port, target_port in valid_connections):
                warnings.append("Connect or remove the buffer tank's second inlet.")
    return list(dict.fromkeys(warnings))


def _component(component_id: str, component_type: str, name: str, *, inlet: bool = True, outlet: bool = True) -> SystemComponent:
    ports: dict[str, Port] = {}
    if inlet:
        ports["in"] = Port("in", "in")
    if outlet:
        ports["out"] = Port("out", "out")
    return SystemComponent(component_id, component_type, name, ports)


def build_system_template(system_type: str) -> RWHSystem:
    components = {
        "collection": _component("collection", "collection", "Collection surfaces", inlet=False),
        "primary": _component("primary", "primary_tank", "Primary tank"),
        "overflow": _component("overflow", "overflow", "Overflow discharge", outlet=False),
        "end_uses": _component("end_uses", "end_uses", "End uses", outlet=False),
        "mains": _component("mains", "mains_backup", "Municipal backup", inlet=False),
    }
    connections = [
        Connection("collection", "out", "primary", "in"),
        Connection("primary", "out", "overflow", "in"),
    ]
    normalized_type = "Indirect system" if system_type == "Indirect system" else "Direct system"
    if normalized_type == "Indirect system":
        components.update(
            {
                "filtration_pump": _component("filtration_pump", "pump", "Filtration pump"),
                "filtration": _component("filtration", "filter", "Filtration"),
                "booster": _component("booster", "booster_tank", "Buffer tank"),
                "booster_pump": _component("booster_pump", "pump", "Booster pump"),
            }
        )
        connections.extend(
            [
                Connection("primary", "out", "filtration_pump", "in"),
                Connection("filtration_pump", "out", "filtration", "in"),
                Connection("filtration", "out", "booster", "in"),
                Connection("mains", "out", "booster", "in"),
                Connection("booster", "out", "booster_pump", "in"),
                Connection("booster_pump", "out", "end_uses", "in"),
            ]
        )
    else:
        components["distribution_pump"] = _component(
            "distribution_pump", "pump", "Distribution pump"
        )
        connections.extend(
            [
                Connection("primary", "out", "distribution_pump", "in"),
                Connection("distribution_pump", "out", "end_uses", "in"),
                Connection("mains", "out", "end_uses", "in"),
            ]
        )
    system = RWHSystem(normalized_type, components, connections)
    errors = system.validate()
    if errors:
        raise ValueError("Invalid rainwater system template: " + " ".join(errors))
    return system
