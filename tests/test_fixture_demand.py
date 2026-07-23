from __future__ import annotations

import pandas as pd
import pytest

from rainwater_app.defaults import default_project_config
from rainwater_app.engine import demand_object_daily_value_for_date, simulate_hourly_tank
from rainwater_app.models import (
    OCCUPANCY_SCHEDULE_TYPE,
    DemandObject,
    fixture_daily_demand_gallons,
)
from rainwater_app.storage import SQLiteStore
from rainwater_app.ui_logic import (
    common_demand_object_templates,
    validated_demand_object_library,
)


def _fixture_object() -> DemandObject:
    return DemandObject(
        "Office toilets",
        "Toilet",
        schedule_name="Always on",
        demand_mode="fixture_usage",
        fixture_people=10.0,
        fixture_uses_per_person_per_day=3.0,
        fixture_volume_gallons_per_use=1.28,
        operating_weekdays=[0, 1, 2, 3, 4],
    )


def test_fixture_daily_demand_multiplies_people_uses_and_volume() -> None:
    assert fixture_daily_demand_gallons(_fixture_object()) == pytest.approx(38.4)


def test_fixture_demand_uses_schedule_as_the_active_day_authority() -> None:
    config = default_project_config()
    config.demand.hourly_schedule_library["Always on"] = {
        day: ([1.0] * 24 if day in {"mon", "tue", "wed", "thu", "fri"} else [0.0] * 24)
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    demand_object = _fixture_object()
    demand_object.operating_weekdays = [5, 6]

    assert demand_object_daily_value_for_date(
        config.demand, demand_object, pd.Timestamp("2025-01-06")
    ) == pytest.approx(38.4)
    assert demand_object_daily_value_for_date(
        config.demand, demand_object, pd.Timestamp("2025-01-11")
    ) == 0.0


def test_hourly_fixture_demand_is_zero_on_an_all_zero_schedule_day() -> None:
    config = default_project_config()
    config.demand.hourly_schedule_library["Always on"] = {
        day: [0.0] * 24
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    config.demand.demand_objects = [_fixture_object()]
    rainfall = pd.DataFrame(
        {"Date": [pd.Timestamp("2025-01-06")], "Precipitation": [0.0]}
    )

    results = simulate_hourly_tank(config, rainfall, tank_size_gallons=100.0)

    assert results["DemandGallons"].sum() == 0.0


def test_hourly_fixture_demand_distributes_the_calculated_daily_volume() -> None:
    config = default_project_config()
    config.demand.hourly_schedule_library["Always on"] = {
        day: [1.0] * 24 for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    config.demand.demand_objects = [_fixture_object()]
    rainfall = pd.DataFrame(
        {"Date": [pd.Timestamp("2025-01-06")], "Precipitation": [0.0]}
    )

    results = simulate_hourly_tank(config, rainfall, tank_size_gallons=100.0)

    assert results["DemandGallons"].sum() == pytest.approx(38.4)


def test_hourly_fixture_demand_is_evenly_divided_across_occupied_hours() -> None:
    config = default_project_config()
    config.demand.hourly_schedule_enabled = True
    config.demand.hourly_schedule_library["Two occupied hours"] = {
        day: [0.0] * 8 + [1.0, 1.0] + [0.0] * 14
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    config.demand.hourly_schedule_types["Two occupied hours"] = (
        OCCUPANCY_SCHEDULE_TYPE
    )
    fixture = _fixture_object()
    fixture.schedule_name = "Two occupied hours"
    fixture.fixture_people = 1.0
    fixture.fixture_uses_per_person_per_day = 1.0
    fixture.fixture_volume_gallons_per_use = 2.0
    config.demand.demand_objects = [fixture]
    rainfall = pd.DataFrame(
        {"Date": [pd.Timestamp("2025-01-06")], "Precipitation": [0.0]}
    )

    results = simulate_hourly_tank(config, rainfall, tank_size_gallons=100.0)

    assert results["DemandGallons"].iloc[8] == pytest.approx(1.0)
    assert results["DemandGallons"].iloc[9] == pytest.approx(1.0)
    assert results["DemandGallons"].sum() == pytest.approx(2.0)


def test_monthly_volume_without_schedule_is_uniform_across_24_hours() -> None:
    config = default_project_config()
    config.demand.hourly_schedule_enabled = True
    config.demand.demand_objects = [DemandObject(
        "Monthly process",
        "Other indoor",
        schedule_name="",
        demand_mode="monthly_volume",
        monthly_demand_gallons={"jan": 310.0},
    )]
    rainfall = pd.DataFrame(
        {"Date": [pd.Timestamp("2025-01-06")], "Precipitation": [0.0]}
    )

    assert demand_object_daily_value_for_date(
        config.demand, config.demand.demand_objects[0], pd.Timestamp("2025-01-06")
    ) == pytest.approx(10.0)
    results = simulate_hourly_tank(config, rainfall, tank_size_gallons=100.0)

    assert results["DemandGallons"].sum() == pytest.approx(10.0)
    assert results["DemandGallons"].tolist() == pytest.approx([10.0 / 24.0] * 24)


def test_builtin_toilet_template_uses_editable_activity_defaults() -> None:
    toilet = common_demand_object_templates()["Toilet"]

    assert toilet.demand_mode == "fixture_usage"
    assert toilet.fixture_people == 1.0
    assert toilet.fixture_uses_per_person_per_day == 3.0
    assert toilet.fixture_volume_gallons_per_use == 1.28


def test_builtin_sink_template_requires_an_explicit_volume_per_use() -> None:
    sink = common_demand_object_templates()["Sink"]

    assert sink.object_type == "Sink"
    assert sink.demand_mode == "fixture_usage"
    assert sink.fixture_people == 1.0
    assert sink.fixture_uses_per_person_per_day == 1.0
    assert sink.fixture_volume_gallons_per_use == 0.0


def test_fixture_fields_are_validated_in_custom_library_payload() -> None:
    library = validated_demand_object_library(
        {
            "Office toilets": {
                "object_type": "Toilet",
                "demand_mode": "fixture_usage",
                "fixture_people": "12",
                "fixture_uses_per_person_per_day": "2.5",
                "fixture_volume_gallons_per_use": "1.1",
            }
        }
    )

    fixture = library["Office toilets"]
    assert fixture.fixture_people == 12.0
    assert fixture.fixture_uses_per_person_per_day == 2.5
    assert fixture.fixture_volume_gallons_per_use == 1.1


def test_fixture_assumptions_round_trip_through_project_storage(tmp_path) -> None:
    config = default_project_config()
    config.name = "Fixture project"
    config.demand.demand_objects = [_fixture_object()]
    store = SQLiteStore(tmp_path / "projects.db", backup_dir=tmp_path / "backups")

    store.save_project(config)
    loaded, _rainfall = store.load_project("Fixture project")

    fixture = loaded.demand.demand_objects[0]
    assert fixture.demand_mode == "fixture_usage"
    assert fixture.fixture_people == 10.0
    assert fixture.fixture_uses_per_person_per_day == 3.0
    assert fixture.fixture_volume_gallons_per_use == 1.28
