# Roadmap

This document records possible future directions for the RWH Calculator. Items are proposals rather than commitments to a particular release.

## Configurable system networks

Develop an OpenStudio-style system editor in which users assemble arbitrary rainwater systems from tanks, pumps, filters, controls, municipal connections, end uses, and discharge components. Each component would expose typed inlet and outlet ports plus capacity, efficiency, storage, and control parameters. A general hourly solver would traverse the connected network and apply conservation of mass at every component and timestep instead of selecting a hard-coded direct or indirect template.

The current direct and indirect templates are the first constrained implementation of this model. Future work should include connection validation, loop detection, deterministic flow priority, controller state, component-level diagnostics, saved reusable templates, and a migration path that preserves existing projects.

## Economic analysis and lifecycle cost

The first economic-analysis release is implemented for the selected tank. It is driven by simulated rainwater supply rather than a user-estimated tank-efficiency factor and supports simple water and sewer tariffs, installed cost, incentives, fixed and percentage annual maintenance, gross and net annual savings, simple payback, and an undiscounted analysis-period net benefit.

The remaining roadmap work is to add end-use-derived sewer eligibility, tiered and time-varying tariffs, candidate-tank financial comparisons, escalation, discounting, equipment replacement, energy consumption, net present value, and internal rate of return.

Implementation requirements include:

- [Implemented] Add project-model fields for currency, water and sewer rates with explicit billing units, installed cost, fixed and percentage maintenance costs, incentives, and analysis period.
- [Implemented] Calculate avoided utility consumption from simulated rainwater delivered to end uses. Do not count overflow, filter loss, unmet demand, municipal makeup, or stored water as savings.
- Define how sewer savings apply by end-use category because irrigation and other outdoor uses may not incur sewer charges.
- Support tiered or time-varying tariffs before presenting results as more than a simple-rate estimate.
- [Implemented for the selected tank] Report annual supplied volume, gross savings, maintenance cost, net savings, and simple payback. A later lifecycle model should add escalation, discount rate, equipment replacement, energy consumption, net present value, and internal rate of return.
- [Implemented on screen] Include units and assumptions in results and distinguish user inputs from calculated outputs. Exported-report integration remains planned.
- [Implemented] Validate negative costs, zero or inconsistent tariff units, non-positive net savings, and payback cases that display as not achieved rather than divide by zero.
- [Partially implemented] Deterministic tests reconcile economic outputs to delivered hydraulic totals and tariff units. End-use-specific outdoor and municipal-backup scenarios remain planned with automatic sewer eligibility.

## First-flush diversion and event losses

Add an explicit first-flush diversion model instead of requiring users to fold this loss into the runoff coefficient. First flush should be triggered by a new rainfall event, not subtracted independently from every wet calendar day.

Implementation requirements include:

- Add first-flush depth or volume to collection-surface parameters, with automatic Imperial and Metric conversion.
- Define a rainfall event using a configurable antecedent dry period. Consecutive wet timesteps within the same event should share one first-flush allowance.
- Track remaining diversion volume through the event and apply it before runoff enters storage.
- Define behavior for multiple collection surfaces and permit either per-surface diverters or one shared downstream diverter.
- Keep first-flush loss separate from runoff coefficient, surface wetting loss, filter loss, tank overflow, and conveyance loss in calculations and reports.
- Report diverted volume by timestep, event, year, and full analysis period.
- Add tests for rainfall below the diversion threshold, multi-timestep storms, storms spanning midnight, dry-period reset, zero diversion, and unit conversion.

## Unusable tank volume and operating levels

The first minimum-operating-level implementation is complete for primary tanks. The simulation distinguishes physical tank capacity from water available for normal withdrawal, and the setting remains separate from initial fill.

Implementation requirements include:

- [Implemented as percentage of capacity] Add a minimum operating level normalized internally to volume. Absolute-volume entry remains planned.
- [Implemented] Prevent normal demand and pump withdrawals from reducing tank level below the minimum operating volume while still including that water in the displayed physical tank level.
- Define whether emergency withdrawal, maintenance drain-down, and overflow calculations use total or usable capacity.
- Apply the same concept consistently to primary and booster tanks where configured.
- Report total capacity, unusable volume, usable capacity, physical water level, usable water available, and unmet demand attributable to the operating limit.
- Migrate existing projects with zero unusable volume so prior results remain unchanged.
- Add boundary tests for empty, partially filled, exactly-at-minimum, full, and oversized minimum-volume configurations.

## Candidate tank performance comparison

Expand the reliability curve dataset into an auditable performance table for every candidate tank size. In addition to reliability, each row should include total demand, rainwater supplied, unmet demand, municipal makeup, overflow, first-flush loss, other treatment losses, and final storage. Economic analysis should add annual savings and payback columns when its inputs are configured.

Implementation requirements include:

- Extend the reliability-curve engine to aggregate the same mass-balance outputs used by the selected-tank simulation rather than running a separate simplified interpretation.
- Preserve cancellation and progress reporting because additional candidate metrics increase calculation cost.
- Add a sortable/exportable comparison table and allow users to promote a candidate to the primary tank without re-entering its size.
- Add a recommendation aid that identifies diminishing reliability gains, but expose the threshold as a user-controlled assumption and avoid presenting it as a universally optimal tank size.
- Include candidate metrics in saved analysis results and invalidate them when rainfall, demand, loss, operating-level, system, or economic inputs change.
- Add reconciliation tests proving that each candidate row matches an independent simulation of the same tank size.

## Rainfall timing and data-resolution clarity

Do not claim that a daily-rainfall analysis accounts for the time of day rainfall occurs. The current hourly demand simulation places each daily rainfall total at the end-of-day boundary. Future true subdaily rainfall support should retain observation timestamps, declare the source resolution, align rainfall and demand time zones, and route collection during the corresponding timestep. Reports should state whether results use daily or subdaily rainfall and identify any temporal allocation assumption.

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
