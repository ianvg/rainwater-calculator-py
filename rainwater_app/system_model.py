from __future__ import annotations

from dataclasses import dataclass, field


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


EDITOR_TYPE_MAP = {
    "rainwater_input": "collection",
    "primary_tank": "primary_tank",
    "filtration_pump": "pump",
    "filtration_system": "filter",
    "booster_tank": "booster_tank",
    "booster_pump": "pump",
    "municipal_backup": "mains_backup",
    "end_uses": "end_uses",
    "overflow_discharge": "overflow",
}


def build_custom_system(
    layout: list[dict[str, object]], connections: list[dict[str, str]]
) -> RWHSystem:
    """Build and validate the constrained hydraulic graph drawn in the system editor."""
    components: dict[str, SystemComponent] = {}
    editor_types: dict[str, str] = {}
    errors: list[str] = []
    for item in layout:
        component_id = str(item.get("id", "")).strip()
        editor_type = str(item.get("component_type", "")).strip()
        if not component_id or editor_type not in EDITOR_TYPE_MAP:
            errors.append("The layout contains an unsupported system object.")
            continue
        if component_id in components:
            errors.append(f"Duplicate component id: {component_id}.")
            continue
        inlet = editor_type not in {"rainwater_input", "municipal_backup"}
        outlet = editor_type not in {"end_uses", "overflow_discharge"}
        components[component_id] = _component(
            component_id,
            EDITOR_TYPE_MAP[editor_type],
            str(item.get("name", component_id)),
            inlet=inlet,
            outlet=outlet,
        )
        components[component_id].properties["editor_type"] = editor_type
        editor_types[component_id] = editor_type

    graph_connections = [
        Connection(
            str(item.get("source_component", "")), "out",
            str(item.get("target_component", "")), "in",
        )
        for item in connections
    ]
    system = RWHSystem("Custom system", components, graph_connections)
    errors.extend(system.validate())

    counts: dict[str, int] = {}
    for editor_type in editor_types.values():
        counts[editor_type] = counts.get(editor_type, 0) + 1
    for required in ("rainwater_input", "primary_tank", "end_uses", "overflow_discharge"):
        if counts.get(required, 0) != 1:
            errors.append(f"Custom system requires exactly one {required.replace('_', ' ')} object.")
    for singular in ("filtration_pump", "filtration_system", "booster_tank", "booster_pump", "municipal_backup"):
        if counts.get(singular, 0) > 1:
            errors.append(f"Custom system supports at most one {singular.replace('_', ' ')} object.")

    adjacency: dict[str, list[str]] = {component_id: [] for component_id in components}
    incoming: dict[str, list[str]] = {component_id: [] for component_id in components}
    for connection in graph_connections:
        if connection.source_component in components and connection.target_component in components:
            adjacency[connection.source_component].append(connection.target_component)
            incoming[connection.target_component].append(connection.source_component)
    for component_id, targets in adjacency.items():
        allowed = 2 if editor_types.get(component_id) == "primary_tank" else 1
        if len(targets) > allowed:
            errors.append(f"{components[component_id].name} has too many outgoing connections.")
    for component_id, sources in incoming.items():
        allowed = 2 if editor_types.get(component_id) in {"booster_tank", "end_uses"} else 1
        if len(sources) > allowed:
            errors.append(f"{components[component_id].name} has too many incoming connections.")

    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(component_id: str) -> None:
        if component_id in visiting:
            errors.append("Custom system connections must not contain a cycle.")
            return
        if component_id in visited:
            return
        visiting.add(component_id)
        for target_id in adjacency.get(component_id, []):
            visit(target_id)
        visiting.remove(component_id)
        visited.add(component_id)
    for component_id in components:
        visit(component_id)

    rainwater_ids = [key for key, value in editor_types.items() if value == "rainwater_input"]
    primary_ids = [key for key, value in editor_types.items() if value == "primary_tank"]
    end_use_ids = [key for key, value in editor_types.items() if value == "end_uses"]
    overflow_ids = [key for key, value in editor_types.items() if value == "overflow_discharge"]
    if rainwater_ids and primary_ids and primary_ids[0] not in adjacency.get(rainwater_ids[0], []):
        errors.append("Rainwater input must connect directly to the primary tank.")
    if primary_ids and overflow_ids and overflow_ids[0] not in adjacency.get(primary_ids[0], []):
        errors.append("Primary tank must connect directly to overflow discharge.")

    def service_path() -> list[str]:
        if not primary_ids or not end_use_ids:
            return []
        target = end_use_ids[0]
        stack = [(primary_ids[0], [primary_ids[0]])]
        while stack:
            node, path = stack.pop()
            if node == target:
                return path
            stack.extend((child, path + [child]) for child in adjacency.get(node, []) if child not in path)
        return []
    path = service_path()
    if not path:
        errors.append("Primary tank must have a connected service path to end uses.")
    else:
        path_types = [editor_types[node] for node in path]
        allowed_order = [
            "primary_tank", "filtration_pump", "filtration_system",
            "booster_tank", "booster_pump", "end_uses",
        ]
        positions = [allowed_order.index(kind) for kind in path_types if kind in allowed_order]
        if positions != sorted(positions) or path_types[0] != "primary_tank" or path_types[-1] != "end_uses":
            errors.append("Service objects are not connected in a valid hydraulic order.")
        for editor_type in ("filtration_pump", "filtration_system", "booster_tank", "booster_pump"):
            if counts.get(editor_type, 0) and editor_type not in path_types:
                errors.append(f"{editor_type.replace('_', ' ').title()} is disconnected from the service path.")
    mains_ids = [key for key, value in editor_types.items() if value == "municipal_backup"]
    if mains_ids:
        targets = adjacency.get(mains_ids[0], [])
        if len(targets) != 1 or editor_types.get(targets[0]) not in {"booster_tank", "end_uses"}:
            errors.append("Municipal backup must connect to the booster tank or end uses.")

    if errors:
        raise ValueError("Invalid custom system:\n- " + "\n- ".join(dict.fromkeys(errors)))
    system.components["__metadata__"] = SystemComponent(
        "__metadata__", "metadata", "Custom graph metadata", {},
        {"service_path": ",".join(editor_types[node] for node in path)},
    )
    return system


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
                "booster": _component("booster", "booster_tank", "Booster tank"),
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
