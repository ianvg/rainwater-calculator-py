from .models import DemandProfile, ProjectConfig, Surface, SystemComponentParameters, TankParameters, MONTH_KEYS

DEFAULT_SURFACES = [
    Surface("Roof membrane", 0.0, 0.95),
    Surface("Roof asphalt shingle", 0.0, 0.9),
    Surface("Roof metal", 0.0, 0.95),
    Surface("Roof green roof", 0.0, 0.6),
    Surface("Roof terracotta", 0.0, 0.9),
    Surface("Non-roof impervious", 0.0, 0.85),
    Surface("Semi-pervious", 0.0, 0.45),
    Surface("Engineered semi-pervious", 0.0, 0.7),
    Surface("Other", 0.0, 0.5),
]


def _month_zero_map() -> dict[str, float]:
    return {m: 0.0 for m in MONTH_KEYS}


def default_surface_runoff(surface_name: str) -> float:
    normalized = surface_name.strip().casefold()
    for surface in DEFAULT_SURFACES:
        if surface.name.casefold() == normalized:
            return surface.runoff_coefficient
    return Surface(name="Default").runoff_coefficient


def default_project_config(name: str = "My Project") -> ProjectConfig:
    surfaces = [Surface(surface.name, surface.area, surface.runoff_coefficient) for surface in DEFAULT_SURFACES]

    demand = DemandProfile(
        male_occupancy=_month_zero_map(),
        female_occupancy=_month_zero_map(),
        ice_making=_month_zero_map(),
        cooling_tower=_month_zero_map(),
        ice_skating=_month_zero_map(),
        other_indoor=_month_zero_map(),
        spray_irrigation=_month_zero_map(),
        drip_irrigation=_month_zero_map(),
        vehicular_washing=_month_zero_map(),
        other_outdoor=_month_zero_map(),
    )

    return ProjectConfig(
        name=name,
        surfaces=surfaces,
        demand=demand,
        tank_parameters=TankParameters(),
        system_parameters=SystemComponentParameters(),
    )
