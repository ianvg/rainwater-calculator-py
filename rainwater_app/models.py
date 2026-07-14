from dataclasses import dataclass, field, asdict
from typing import Dict, List

MONTH_KEYS = [
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]


@dataclass
class Surface:
    name: str
    area: float = 0.0
    runoff_coefficient: float = 0.9


@dataclass
class DemandProfile:
    avg_flush_per_person: float = 0.0
    gallons_per_flush_toilet: float = 0.0
    gallons_per_flush_urinal: float = 0.0
    simple_daily_demand_gallons: float = 0.0
    male_occupancy: Dict[str, float] = field(default_factory=dict)
    female_occupancy: Dict[str, float] = field(default_factory=dict)
    ice_making: Dict[str, float] = field(default_factory=dict)
    cooling_tower: Dict[str, float] = field(default_factory=dict)
    ice_skating: Dict[str, float] = field(default_factory=dict)
    other_indoor: Dict[str, float] = field(default_factory=dict)
    spray_irrigation: Dict[str, float] = field(default_factory=dict)
    drip_irrigation: Dict[str, float] = field(default_factory=dict)
    vehicular_washing: Dict[str, float] = field(default_factory=dict)
    other_outdoor: Dict[str, float] = field(default_factory=dict)


@dataclass
class TankParameters:
    initial_fill_percent: float = 50.0
    reliable_fill_percent: float = 25.0


@dataclass
class ProjectConfig:
    name: str
    unit_system: str = "Imperial"
    country_code: str = "USA"
    surfaces: List[Surface] = field(default_factory=list)
    demand: DemandProfile = field(default_factory=DemandProfile)
    graph_start_gal: int = 500
    graph_end_gal: int = 20000
    graph_step_gal: int = 500
    selected_tank_size_gal: float = 5000.0
    rainfall_source_label: str | None = None
    tank_parameters: TankParameters = field(default_factory=TankParameters)

    def to_dict(self) -> Dict:
        return asdict(self)
