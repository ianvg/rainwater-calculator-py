from __future__ import annotations

import pandas as pd
import pytest

from rainwater_app.defaults import default_project_config
from rainwater_app.engine import demand_object_daily_value_for_date, simulate_hourly_tank
from rainwater_app.models import DemandObject, fixture_daily_demand_gallons
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


def test_fixture_demand_respects_operating_weekdays() -> None:
    config = default_project_config()
    config.demand.hourly_schedule_library["Always on"] = {
        day: [1.0] * 24 for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    demand_object = _fixture_object()

    assert demand_object_daily_value_for_date(
        config.demand, demand_object, pd.Timestamp("2025-01-06")
    ) == pytest.approx(38.4)
    assert demand_object_daily_value_for_date(
        config.demand, demand_object, pd.Timestamp("2025-01-11")
    ) == 0.0


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


def test_builtin_toilet_template_uses_editable_activity_defaults() -> None:
    toilet = common_demand_object_templates()["Toilet"]

    assert toilet.demand_mode == "fixture_usage"
    assert toilet.fixture_people == 1.0
    assert toilet.fixture_uses_per_person_per_day == 3.0
    assert toilet.fixture_volume_gallons_per_use == 1.28


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
