# Roadmap

This document records possible future directions for the RWH Calculator. Items are proposals rather than commitments to a particular release.

## International rainfall data

Extend rainfall importing beyond the current US ACIS and Canadian ECCC workflows using a layered provider strategy:

1. Prefer official national weather services when they provide authoritative historical station observations and a practical API.
2. Use [Meteostat](https://dev.meteostat.net/python/) as a general station-observation provider for countries without a dedicated integration.
3. Offer [Open-Meteo historical weather](https://open-meteo.com/en/docs/historical-weather-api) as a coordinate-based fallback where station records are unavailable or incomplete.

Meteostat provides a Python interface backed by Pandas and standardizes precipitation in millimetres. Its station coverage and record completeness vary by country, and its daily precipitation data does not consistently distinguish rain from snowfall water equivalent across all underlying providers.

Open-Meteo can provide gap-free global precipitation, rain, and snowfall series. Its historical product is gridded reanalysis data rather than a direct station observation, so the application must not present it as measured station data.

### Proposed provider interface

Each integration should implement a common interface for station discovery and daily rainfall retrieval:

```python
class RainfallProvider:
    def search_stations(self, region, query): ...
    def fetch_daily(self, station, start_date, end_date, precipitation_basis): ...
```

Provider results should be normalized to include:

- observation date
- precipitation amount in the calculator's internal units
- source provider
- source station ID and name, when applicable
- precipitation basis, such as total precipitation or rain only
- data type: observed, interpolated, or gridded reanalysis
- missing-value and quality information supplied by the provider

The import screen and saved project should retain this provenance. Results and reports should identify whether rainfall is observed station data, interpolated data, or gridded reanalysis data.

Before enabling a provider in a distributed or hosted production release, verify its current API terms, data licensing, attribution requirements, rate limits, and commercial-use conditions.

## Address lookup and geocoding

The project settings currently retain structured street, locality, administrative-region, postcode, and ISO country components without transmitting them to an external service. A future explicit **Find address** action could convert those components to coordinates for nearby weather-station searches. Country-specific rendering could use ISO 19160-4 / UPU S42 templates rather than assuming one universal address order.

Possible OpenStreetMap-based approaches include:

- Nominatim forward geocoding for free-form or structured address searches
- Nominatim reverse geocoding from coordinates to an address
- a self-hosted Nominatim instance for controlled production use
- an OSM-based hosted provider that supports autocomplete, service guarantees, and application-specific API keys
- Photon or Pelias when richer autocomplete or multi-source indexing is required

The public OpenStreetMap Foundation Nominatim endpoint is suitable only for moderate, user-triggered searches under its usage policy. It must not be used for client-side autocomplete, is limited to one request per second, requires an identifying user agent and attribution, and should be replaceable without an application update. Addresses can be sensitive, so lookup must be initiated explicitly and the UI should disclose the selected provider before transmitting an address.

Other production options include commercial geocoding and address-validation APIs. Provider selection should account for geographic coverage, address validation versus coordinate lookup, autocomplete support, result-storage rights, privacy, pricing, offline requirements, and whether coordinates may be saved permanently in project files. A Python adapter can use direct HTTP requests or a provider-neutral client such as GeoPy, but the underlying service's terms still govern usage.
