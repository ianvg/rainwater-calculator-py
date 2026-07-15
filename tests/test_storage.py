from rainwater_app.storage import SQLiteStore


def test_legacy_project_defaults_to_united_states() -> None:
    config = SQLiteStore._config_from_dict({"name": "Legacy project"})

    assert config.country_code == "USA"
    assert config.system_type == "Direct system"
    assert config.author_name == ""
    assert config.notes == ""
    assert config.street_address == ""
    assert config.city == ""
    assert config.state_or_province == ""
    assert config.postal_code == ""
    assert config.acis_precipitation_field == "TOTAL_PRECIPITATION"


def test_project_country_code_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {"name": "Canadian project", "country_code": "CAN", "canadian_precipitation_field": "TOTAL_RAIN"}
    )

    assert config.country_code == "CAN"
    assert config.canadian_precipitation_field == "TOTAL_RAIN"


def test_project_system_type_is_loaded() -> None:
    config = SQLiteStore._config_from_dict({"name": "Indirect project", "system_type": "Indirect system"})

    assert config.system_type == "Indirect system"


def test_project_author_name_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {"name": "Authored project", "author_name": "Jane Engineer", "notes": "First line\nSecond line"}
    )

    assert config.author_name == "Jane Engineer"
    assert config.notes == "First line\nSecond line"


def test_acis_precipitation_field_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {"name": "US project", "country_code": "USA", "acis_precipitation_field": "TOTAL_RAIN"}
    )

    assert config.acis_precipitation_field == "TOTAL_RAIN"


def test_structured_project_address_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Addressed project",
            "street_address": "1121 Brittain Estates Drive",
            "city": "Kingsport",
            "state_or_province": "Tennessee",
            "postal_code": "37664",
            "latitude": 36.548921,
            "longitude": -82.456789,
        }
    )

    assert config.street_address == "1121 Brittain Estates Drive"
    assert config.city == "Kingsport"
    assert config.state_or_province == "Tennessee"
    assert config.postal_code == "37664"
    assert config.latitude == 36.548921
    assert config.longitude == -82.456789


def test_comparison_tank_sizes_are_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {
            "name": "Comparison project",
            "multitank_comparison_enabled": True,
            "comparison_tank_sizes_gal": [2500, 5000.5, 10000],
            "analysis_unit_system": "Metric",
        }
    )

    assert config.multitank_comparison_enabled is True
    assert config.comparison_tank_sizes_gal == [2500.0, 5000.5, 10000.0]
    assert config.analysis_unit_system == "Metric"


def test_single_field_address_migrates_to_street_address() -> None:
    config = SQLiteStore._config_from_dict(
        {"name": "Earlier address project", "address": "1121 Brittain Estates Drive"}
    )

    assert config.street_address == "1121 Brittain Estates Drive"


def test_analysis_input_signature_is_loaded() -> None:
    config = SQLiteStore._config_from_dict(
        {"name": "Analyzed project", "analysis_input_signature": "signature-from-last-run"}
    )

    assert config.analysis_input_signature == "signature-from-last-run"
