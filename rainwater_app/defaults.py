from .models import DemandProfile, ProjectConfig, Surface, TankParameters, MONTH_KEYS


def _month_zero_map() -> dict[str, float]:
    return {m: 0.0 for m in MONTH_KEYS}


def default_project_config(name: str = "My Project") -> ProjectConfig:
    surfaces = [
        Surface("Roof Membrane", 0.0, 0.95),
        Surface("Roof Asphalt Shingle", 0.0, 0.9),
        Surface("Roof Metal", 0.0, 0.95),
        Surface("Roof Green Roof", 0.0, 0.6),
        Surface("Roof Terracotta", 0.0, 0.9),
        Surface("Non-Roof Impervious", 0.0, 0.85),
        Surface("Semi-Pervious", 0.0, 0.45),
        Surface("Engineered Semi-Pervious", 0.0, 0.7),
        Surface("Other", 0.0, 0.5),
    ]

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
    )
