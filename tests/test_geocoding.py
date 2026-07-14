from rainwater_app.geocoding import _address_from_nominatim


def test_nominatim_address_is_mapped_to_project_fields() -> None:
    result = _address_from_nominatim(
        {
            "display_name": "1121 Brittain Estates Drive, Kingsport, Tennessee 37664, United States",
            "address": {
                "house_number": "1121",
                "road": "Brittain Estates Drive",
                "city": "Kingsport",
                "state": "Tennessee",
                "postcode": "37664",
                "country_code": "us",
            },
        }
    )

    assert result["street_address"] == "1121 Brittain Estates Drive"
    assert result["city"] == "Kingsport"
    assert result["state_or_province"] == "Tennessee"
    assert result["postal_code"] == "37664"
    assert result["country_code_alpha2"] == "US"


def test_nominatim_address_accepts_non_city_locality_and_province() -> None:
    result = _address_from_nominatim(
        {"address": {"road": "Main Street", "village": "Example", "province": "Ontario", "country_code": "ca"}}
    )

    assert result["city"] == "Example"
    assert result["state_or_province"] == "Ontario"
    assert result["country_code_alpha2"] == "CA"
