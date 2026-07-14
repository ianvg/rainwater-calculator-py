from rainwater_app.storage import SQLiteStore


def test_legacy_project_defaults_to_united_states() -> None:
    config = SQLiteStore._config_from_dict({"name": "Legacy project"})

    assert config.country_code == "USA"
    assert config.acis_precipitation_field == "TOTAL_PRECIPITATION"


def test_project_country_code_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {"name": "Canadian project", "country_code": "CAN", "canadian_precipitation_field": "TOTAL_RAIN"}
    )

    assert config.country_code == "CAN"
    assert config.canadian_precipitation_field == "TOTAL_RAIN"


def test_acis_precipitation_field_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {"name": "US project", "country_code": "USA", "acis_precipitation_field": "TOTAL_RAIN"}
    )

    assert config.acis_precipitation_field == "TOTAL_RAIN"
