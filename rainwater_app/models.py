from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List

MONTH_KEYS = [
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]
WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def default_hourly_weekly_fractions() -> Dict[str, List[float]]:
    return {day: [1.0 / 24.0] * 24 for day in WEEKDAY_KEYS}


def common_hourly_schedule_templates() -> Dict[str, Dict[str, List[float]]]:
    weekday_business_hours = {
        day: ([0.0] * 8 + [1.0 / 9.0] * 9 + [0.0] * 7) if day in WEEKDAY_KEYS[:5] else [0.0] * 24
        for day in WEEKDAY_KEYS
    }
    return {
        "Always on": default_hourly_weekly_fractions(),
        "Always off": {day: [0.0] * 24 for day in WEEKDAY_KEYS},
        "8 AM to 5 PM weekdays": weekday_business_hours,
    }


@dataclass
class Surface:
    name: str
    area: float = 0.0
    runoff_coefficient: float = 0.9

    def __post_init__(self) -> None:
        self.runoff_coefficient = float(
            Decimal(str(self.runoff_coefficient)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )


@dataclass
class DemandProfile:
    avg_flush_per_person: float = 0.0
    gallons_per_flush_toilet: float = 0.0
    gallons_per_flush_urinal: float = 0.0
    simple_daily_demand_gallons: float = 0.0
    daily_demand_days_per_week: int = 7
    hourly_schedule_enabled: bool = False
    hourly_weekly_fractions: Dict[str, List[float]] = field(default_factory=default_hourly_weekly_fractions)
    hourly_schedule_library: Dict[str, Dict[str, List[float]]] = field(default_factory=dict)
    active_hourly_schedule_name: str = "Typical week demand"
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
class SystemComponentParameters:
    pump_capacity_gallons_per_hour: float = 0.0
    filtration_pump_capacity_gallons_per_hour: float = 1200.0
    filter_recovery_percent: float = 100.0
    booster_tank_size_gallons: float = 0.0
    booster_initial_fill_percent: float = 0.0
    booster_refill_level_percent: float = 50.0
    municipal_backup_enabled: bool = True


@dataclass
class ProjectConfig:
    name: str
    author_name: str = ""
    notes: str = ""
    street_address: str = ""
    city: str = ""
    state_or_province: str = ""
    postal_code: str = ""
    latitude: float | None = None
    longitude: float | None = None
    unit_system: str = "Imperial"
    country_code: str = "USA"
    system_type: str = "Direct system"
    acis_precipitation_field: str = "TOTAL_PRECIPITATION"
    canadian_precipitation_field: str = "TOTAL_PRECIPITATION"
    surfaces: List[Surface] = field(default_factory=list)
    demand: DemandProfile = field(default_factory=DemandProfile)
    graph_start_gal: int = 500
    graph_end_gal: int = 20000
    graph_step_gal: int = 500
    graph_auto_step_count: int = 20
    selected_tank_size_gal: float = 5000.0
    multitank_comparison_enabled: bool = False
    comparison_tank_sizes_gal: List[float] = field(default_factory=list)
    rainfall_source_label: str | None = None
    analysis_input_signature: str | None = None
    analysis_unit_system: str | None = None
    tank_parameters: TankParameters = field(default_factory=TankParameters)
    system_parameters: SystemComponentParameters = field(default_factory=SystemComponentParameters)

    def to_dict(self) -> Dict:
        return asdict(self)
