from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List

MONTH_KEYS = [
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]
WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_TOILET_FLUSHES_PER_PERSON_PER_DAY = 3.0
DEFAULT_TOILET_VOLUME_GALLONS_PER_FLUSH = 1.28


def default_hourly_weekly_fractions() -> Dict[str, List[float]]:
    return {day: [1.0] * 24 for day in WEEKDAY_KEYS}


def common_hourly_schedule_templates() -> Dict[str, Dict[str, List[float]]]:
    weekday_business_hours = {
        day: ([0.0] * 8 + [1.0] * 9 + [0.0] * 7) if day in WEEKDAY_KEYS[:5] else [0.0] * 24
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
    first_flush_depth_inches: float = 0.0

    def __post_init__(self) -> None:
        self.runoff_coefficient = float(
            Decimal(str(self.runoff_coefficient)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        self.first_flush_depth_inches = max(float(self.first_flush_depth_inches), 0.0)


def default_sewer_eligible_for_object_type(object_type: str) -> bool:
    """Return the conservative billing default for a demand-object type."""
    return object_type.casefold() != "irrigation system"


@dataclass
class DemandObject:
    name: str
    object_type: str = "Other"
    instantaneous_demand_gallons_per_minute: float = 0.0
    schedule_name: str = ""
    demand_mode: str = "scheduled_flow"
    recurring_daily_gallons: float = 0.0
    fixture_people: float = 0.0
    fixture_uses_per_person_per_day: float = 0.0
    fixture_volume_gallons_per_use: float = 0.0
    operating_days_per_week: int = 7
    monthly_daily_demand_gallons: Dict[str, float] = field(default_factory=dict)
    monthly_demand_gallons: Dict[str, float] = field(default_factory=dict)
    sewer_eligible: bool | None = None
    uses_legacy_sewer_eligibility: bool = False
    operating_weekdays: List[int] | None = None

    def __post_init__(self) -> None:
        if self.sewer_eligible is None:
            self.sewer_eligible = default_sewer_eligible_for_object_type(self.object_type)
        if self.operating_weekdays is None:
            day_count = min(max(int(self.operating_days_per_week), 0), 7)
            self.operating_weekdays = list(range(day_count))
        else:
            normalized_weekdays: set[int] = set()
            for day in self.operating_weekdays:
                try:
                    value = int(day)
                except (TypeError, ValueError):
                    continue
                if 0 <= value <= 6:
                    normalized_weekdays.add(value)
            self.operating_weekdays = sorted(normalized_weekdays)
            self.operating_days_per_week = len(self.operating_weekdays)


def fixture_daily_demand_gallons(demand_object: DemandObject) -> float:
    """Return activity-based daily fixture demand in internal gallons."""
    return (
        max(float(demand_object.fixture_people), 0.0)
        * max(float(demand_object.fixture_uses_per_person_per_day), 0.0)
        * max(float(demand_object.fixture_volume_gallons_per_use), 0.0)
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
    demand_objects: List[DemandObject] = field(default_factory=list)
    legacy_inputs_migrated: bool = False
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


def migrate_legacy_demand_inputs(demand: DemandProfile) -> list[int]:
    """Convert aggregate simple/monthly inputs to equivalent demand objects once."""
    if demand.legacy_inputs_migrated:
        return []
    schedule_name = demand.active_hourly_schedule_name
    if schedule_name not in demand.hourly_schedule_library:
        demand.hourly_schedule_library[schedule_name] = {
            day: list(values) for day, values in demand.hourly_weekly_fractions.items()
        }
    created: list[int] = []

    def add(item: DemandObject) -> None:
        item.uses_legacy_sewer_eligibility = True
        demand.demand_objects.append(item)
        created.append(len(demand.demand_objects) - 1)

    simple_daily = max(float(demand.simple_daily_demand_gallons), 0.0)
    if simple_daily > 0.0:
        add(DemandObject(
            "Simple recurring demand", "Other", schedule_name=schedule_name,
            demand_mode="recurring_daily", recurring_daily_gallons=simple_daily,
            operating_days_per_week=min(max(int(demand.daily_demand_days_per_week), 0), 7),
        ))

    toilet_daily: Dict[str, float] = {}
    urinal_daily: Dict[str, float] = {}
    for month in MONTH_KEYS:
        male = max(float(demand.male_occupancy.get(month, 0.0)), 0.0)
        female = max(float(demand.female_occupancy.get(month, 0.0)), 0.0)
        flushes = max(float(demand.avg_flush_per_person), 0.0)
        toilet_daily[month] = (
            female * flushes * max(float(demand.gallons_per_flush_toilet), 0.0)
            + 0.5 * male * flushes * max(float(demand.gallons_per_flush_toilet), 0.0)
        )
        urinal_daily[month] = (
            0.5 * male * flushes * max(float(demand.gallons_per_flush_urinal), 0.0)
        )
    operating_days = min(max(int(demand.daily_demand_days_per_week), 0), 7)
    if any(value > 0.0 for value in toilet_daily.values()):
        add(DemandObject(
            "Toilet demand", "Toilet", schedule_name=schedule_name,
            demand_mode="recurring_daily", operating_days_per_week=operating_days,
            monthly_daily_demand_gallons=toilet_daily,
        ))
    if any(value > 0.0 for value in urinal_daily.values()):
        add(DemandObject(
            "Urinal demand", "Urinal", schedule_name=schedule_name,
            demand_mode="recurring_daily", operating_days_per_week=operating_days,
            monthly_daily_demand_gallons=urinal_daily,
        ))

    categories = (
        ("ice_making", "Ice making", "Ice making"),
        ("cooling_tower", "Cooling tower", "Cooling tower"),
        ("ice_skating", "Ice skating", "Ice skating"),
        ("other_indoor", "Other indoor", "Other indoor"),
        ("spray_irrigation", "Spray irrigation", "Irrigation system"),
        ("drip_irrigation", "Drip irrigation", "Irrigation system"),
        ("vehicular_washing", "Vehicle washing", "Vehicle washing"),
        ("other_outdoor", "Other outdoor", "Other outdoor"),
    )
    for field_name, name, object_type in categories:
        values = {
            month: max(float(getattr(demand, field_name).get(month, 0.0)), 0.0)
            for month in MONTH_KEYS
        }
        if any(value > 0.0 for value in values.values()):
            add(DemandObject(
                name, object_type, schedule_name=schedule_name,
                demand_mode="monthly_volume", monthly_demand_gallons=values,
            ))

    demand.simple_daily_demand_gallons = 0.0
    demand.avg_flush_per_person = 0.0
    demand.gallons_per_flush_toilet = 0.0
    demand.gallons_per_flush_urinal = 0.0
    for field_name in (
        "male_occupancy", "female_occupancy", "ice_making", "cooling_tower",
        "ice_skating", "other_indoor", "spray_irrigation", "drip_irrigation",
        "vehicular_washing", "other_outdoor",
    ):
        setattr(demand, field_name, {month: 0.0 for month in MONTH_KEYS})
    demand.legacy_inputs_migrated = True
    return created


@dataclass
class TankParameters:
    initial_fill_percent: float = 50.0
    minimum_operating_volume_percent: float = 0.0


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
class FinancialParameters:
    currency: str = "USD"
    water_rate: float = 0.0
    sewer_rate: float = 0.0
    tariff_billing_unit: str = "per 1,000 gal"
    sewer_eligible_percent: float = 100.0
    installed_cost: float = 0.0
    incentives: float = 0.0
    fixed_annual_maintenance: float = 0.0
    annual_maintenance_percent: float = 0.0
    analysis_period_years: int = 20
    discount_rate_percent: float = 5.0
    utility_rate_escalation_percent: float = 0.0
    maintenance_escalation_percent: float = 0.0
    electricity_escalation_percent: float = 0.0
    pump_power_kw: float = 0.0
    pump_flow_rate_gallons_per_hour: float = 0.0
    equipment_replacement_cost: float = 0.0
    equipment_replacement_interval_years: int = 0
    equipment_replacement_escalation_percent: float = 0.0


@dataclass
class OptimizationParameters:
    minimum_reliability_percent: float = 80.0
    electricity_rate_per_kwh: float = 0.15
    objective: str = "Simple payback"
    maximum_annual_municipal_makeup_gallons: float | None = None
    maximum_installed_cost: float | None = None
    require_positive_net_savings: bool = False
    catalog: List[Dict[str, object]] = field(default_factory=list)


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
    system_layout: List[Dict[str, object]] = field(default_factory=list)
    system_connections: List[Dict[str, str]] = field(default_factory=list)
    acis_precipitation_field: str = "TOTAL_PRECIPITATION"
    canadian_precipitation_field: str = "TOTAL_PRECIPITATION"
    surfaces: List[Surface] = field(default_factory=list)
    first_flush_antecedent_dry_days: float = 1.0
    first_flush_antecedent_dry_unit: str = "days"
    demand: DemandProfile = field(default_factory=DemandProfile)
    graph_start_gal: int = 500
    graph_end_gal: int = 20000
    graph_step_gal: int = 500
    graph_auto_step_count: int = 20
    selected_tank_size_gal: float = 5000.0
    recommendation_reliability_target_percent: float = 90.0
    recommendation_marginal_gain_threshold: float = 1.0
    multitank_comparison_enabled: bool = False
    comparison_tank_sizes_gal: List[float] = field(default_factory=list)
    use_synthetic_hourly_rainfall: bool = False
    rainfall_source_label: str | None = None
    rainfall_data_type: str = "unclassified"
    rainfall_temporal_resolution: str = "daily"
    rainfall_timezone: str = "Unspecified"
    rainfall_timing_type: str = "Daily totals; within-day timing not observed"
    rainfall_retrieved_at: str | None = None
    rainfall_known_missing_dates: List[str] = field(default_factory=list)
    weather_station_latitude: float | None = None
    weather_station_longitude: float | None = None
    analysis_input_signature: str | None = None
    analysis_unit_system: str | None = None
    tank_parameters: TankParameters = field(default_factory=TankParameters)
    system_parameters: SystemComponentParameters = field(default_factory=SystemComponentParameters)
    financial_parameters: FinancialParameters = field(default_factory=FinancialParameters)
    optimization_parameters: OptimizationParameters = field(default_factory=OptimizationParameters)

    def to_dict(self) -> Dict:
        return asdict(self)
