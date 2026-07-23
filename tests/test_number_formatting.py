from rainwater_app.defaults import default_project_config
from rainwater_app.number_formatting import (
    EUROPEAN_NUMBER_FORMAT,
    US_NUMBER_FORMAT,
    format_number,
    parse_number,
    set_active_number_format,
)


def test_imperial_general_numbers_group_thousands_and_trim_zero_decimals() -> None:
    set_active_number_format(US_NUMBER_FORMAT)
    config = default_project_config()

    assert format_number(1000, config) == "1,000"
    assert format_number(1000.5, config) == "1,000.5"
    assert format_number(12.340, config) == "12.34"


def test_us_format_is_independent_of_project_units_and_country() -> None:
    set_active_number_format(US_NUMBER_FORMAT)
    config = default_project_config()
    config.unit_system = "Metric (SI)"
    config.country_code = "FRA"

    assert format_number(3785.0, config) == "3,785"
    assert format_number(3785.25, config) == "3,785.25"


def test_european_general_numbers_use_period_grouping_and_decimal_comma() -> None:
    set_active_number_format(EUROPEAN_NUMBER_FORMAT)
    config = default_project_config()

    assert format_number(3785.0, config) == "3.785"
    assert format_number(3785.25, config) == "3.785,25"


def test_displayed_comma_grouping_can_be_parsed_back() -> None:
    set_active_number_format(US_NUMBER_FORMAT)
    assert parse_number("1,234.5") == 1234.5


def test_displayed_european_number_can_be_parsed_back() -> None:
    set_active_number_format(EUROPEAN_NUMBER_FORMAT)
    assert parse_number("1.234,5") == 1234.5


def teardown_module() -> None:
    set_active_number_format(US_NUMBER_FORMAT)
