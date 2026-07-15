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
