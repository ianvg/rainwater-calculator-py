import pytest

from rainwater_app import geocoding
from rainwater_app.geocoding import _address_from_nominatim, _coordinates_from_nominatim


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


def test_nominatim_coordinates_are_parsed() -> None:
    result = _coordinates_from_nominatim(
        {"lat": "36.548921", "lon": "-82.456789", "display_name": "Kingsport, Tennessee"}
    )

    assert result == {
        "latitude": 36.548921,
        "longitude": -82.456789,
        "display_name": "Kingsport, Tennessee",
    }


def test_nominatim_coordinates_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="invalid coordinate"):
        _coordinates_from_nominatim({"lat": "not-a-number", "lon": "-82.4"})


def test_forward_geocoder_uses_structured_address_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, object]] = []

    def fake_search(parameters: dict[str, object]) -> list[dict[str, str]]:
        requests.append(parameters)
        return [{"lat": "33.8855057", "lon": "-83.3756241"}]

    monkeypatch.setattr(geocoding, "_nominatim_search", fake_search)
    result = geocoding.geocode_osm_address(
        "1121 Brittain Estates Drive, Watkinsville, GA 30677, United States",
        "US",
        {
            "street": "1121 Brittain Estates Drive",
            "city": "Watkinsville",
            "state": "GA",
            "postalcode": "30677",
            "country": "United States",
        },
    )

    assert result["latitude"] == pytest.approx(33.8855057)
    assert requests[0]["street"] == "1121 Brittain Estates Drive"
    assert requests[0]["postalcode"] == "30677"
    assert requests[0]["countrycodes"] == "us"


def test_forward_geocoder_relaxes_query_after_no_structured_match(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, object]] = []

    def fake_search(parameters: dict[str, object]) -> list[dict[str, str]]:
        requests.append(parameters)
        return [] if len(requests) < 3 else [{"lat": "33.8", "lon": "-83.3"}]

    monkeypatch.setattr(geocoding, "_nominatim_search", fake_search)
    geocoding.geocode_osm_address(
        "1121 Brittain Estates Drive, Watkinsville, GA, 30677, United States",
        "US",
        {
            "street": "1121 Brittain Estates Drive",
            "city": "Watkinsville",
            "state": "GA",
            "postalcode": "30677",
            "country": "United States",
        },
    )

    assert "q" not in requests[0]
    assert requests[1]["q"].startswith("1121 Brittain Estates Drive, Watkinsville")
    assert requests[2]["q"] == "1121 Brittain Estates Drive, 30677, United States"
