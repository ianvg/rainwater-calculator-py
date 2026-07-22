# Roadmap

This document records possible future directions for the RWH Calculator. Items are proposals rather than commitments to a particular release.

## Architecture modularization and quality gates

[In progress] Reduce the size and responsibility of `tkinter_app.py` through behavior-preserving extractions. Financial analysis, candidate-table preparation, hydraulic analysis coordination, and HTML, LaTeX, and direct-PDF rendering now live in tested UI-independent services. Pure report-model helpers remain in `rainwater_app/reporting.py`, and shared form conversion and validation remain in `rainwater_app/ui_logic.py`. Existing desktop call sites retain compatibility while tests target the extracted modules directly.

Continue extracting cohesive boundaries instead of performing a single wholesale rewrite:

- [Implemented] Keep validated HTML, LaTeX, and direct-PDF renderers behind a dedicated reporting service.
- Separate system-builder canvas interaction from graph validation and compilation.
- [Implemented] Isolate hydraulic analysis coordination, cancellation callbacks, and progress events from widgets.
- Move reusable chart data preparation away from Tkinter drawing code.
- Keep dialogs and tab construction thin, with calculation and validation logic independently testable.
- Add characterization tests before moving UI behavior whose expected output is not already covered.

[Implemented initial gate] Run tests and static checks for pushes and pull requests, build the documentation strictly, and import/smoke-test the desktop entry point on Windows. The manually triggered executable build must run the tests before packaging and smoke-test the packaged executable before uploading it. Future quality work should add coverage reporting, dependency auditing, and targeted visual tests for high-risk Tkinter screens.

## Prioritized product and platform upgrades

### Decision-support recommendations

[Implemented initial release] The candidate-results screen identifies the smallest capacity meeting a user-defined reliability target, a diminishing-returns knee based on an editable marginal-gain threshold, the lowest-payback candidate with a finite payback, and nearby alternatives. The settings are saved without invalidating hydraulic results, and recommendations disclose their governing assumptions rather than label one tank size as universally optimal.

[Partially implemented] Prominent review conditions cover incomplete and missing rainfall records, low selected-tank reliability, overflow above the documented review threshold, and unconfigured economics. Recommendations and warnings appear on screen and in HTML, LaTeX, and direct PDF reports. High municipal makeup and additional project-specific thresholds remain future work; stale-result warnings continue to use the existing Results warning.

### Report architecture and accessibility

[Implemented initial architecture] HTML, LaTeX, and direct PDF rendering now share a validated report model with an explicit schema version. Exports use atomic replacement, HTML is portable without online map or library dependencies, and every HTML chart has a corresponding data table. The model uses report schema version 2 and rejects unsupported versions, missing required fields, and non-finite values. Continuing renderer extraction, broader schema migration rules, and visual/accessibility automation are tracked in [Report improvements](roadmap/report-improvements.md).

### Complete lifecycle economics

[Implemented] Extend simple payback to year-end discounted lifecycle cash flow with utility, maintenance, electricity, and replacement-cost escalation; discount rate; pump energy derived from simulated flow; recurring equipment replacement; nominal net benefit; discounted payback; net present value; and internal rate of return. IRR is withheld for non-conventional cash flows with multiple sign changes. Selected-tank, candidate, optimization, and report calculations share the same lifecycle engine.

[Not started] Add tiered and time-varying tariffs only with explicit billing periods, baseline municipal consumption, fixed-charge treatment, tier allocation rules, and tests that reconcile avoided charges to simulated end-use supply. Component-specific maintenance schedules, financing, taxes, depreciation, and terminal residual value also remain future work.

### Rainfall quality and provenance

[Implemented] Record-completeness scoring, explicit partial-year and missing-period warnings, temporal-resolution and timezone metadata, labels for observed, synthetic, interpolated, and gridded-reanalysis data, and rainfall-event and yearly summaries are available in the desktop workflow and all report formats. Provider-reported missing dates and import timestamps are retained with the project.

[Not started] International providers should implement the common interface described below and preserve source, station, precipitation basis, quality flags, licensing attribution, and retrieval metadata with the project. The quality work above intentionally leaves the existing ACIS and ECCC integrations separate.

### Windows distribution and project safety

[Implemented] Writable state uses native per-user application-data and cache locations on Windows, macOS, and Linux, with environment overrides for managed or portable deployments. First startup atomically copies legacy beside-application files without deleting them. SQLite and project payloads have explicit schema versions; full-synchronous WAL transactions, validated rotating backups, integrity checks, automatic restoration, and damaged-file quarantine cover interrupted writes and corruption. A per-user Inno Setup installer and documented uninstall behavior preserve user projects and backups. Binary signing, release checksums, and any future automatic-update mechanism remain release-engineering work.

### Interface strategy

[Implemented] Tkinter is the complete supported product for authoring, analysis, optimization, persistence, and reporting. Streamlit is a deliberately limited, read-only saved-project viewer and does not own calculation or editing workflows. The legacy Flask entry point, templates, authentication prototype, dependencies, and launchers have been retired. New product features belong in Tkinter and shared domain modules; the viewer may expose saved outputs without creating a parallel implementation.

## Configurable system networks

Develop an OpenStudio-style system editor in which users assemble arbitrary rainwater systems from tanks, pumps, filters, controls, municipal connections, end uses, and discharge components. Each component would expose typed inlet and outlet ports plus capacity, efficiency, storage, and control parameters. A general hourly solver would traverse the connected network and apply conservation of mass at every component and timestep instead of selecting a hard-coded direct or indirect template.

The current direct and indirect templates are the first constrained implementation of this model. Future work should include connection validation, loop detection, deterministic flow priority, controller state, component-level diagnostics, saved reusable templates, and a migration path that preserves existing projects.

## Economic analysis and lifecycle cost

Lifecycle economics are implemented for selected tanks, reliability-curve candidates, and indirect-system optimization. The calculation is driven by simulated rainwater supply and pump flow rather than user-estimated tank efficiency.

The remaining roadmap work includes tiered and time-varying tariffs, component-specific maintenance schedules, financing, taxes, depreciation, and terminal residual value.

Implementation requirements include:

- [Implemented] Add project-model fields for currency, water and sewer rates with explicit billing units, installed cost, fixed and percentage maintenance costs, incentives, and analysis period.
- [Implemented] Calculate avoided utility consumption from simulated rainwater delivered to end uses. Do not count overflow, filter loss, unmet demand, municipal makeup, or stored water as savings.
- [Implemented] Define sewer eligibility on each demand object. Irrigation defaults to exempt, users can override the billing assumption, and supplied rainwater is allocated proportionally when demand is only partially met.
- Support tiered or time-varying tariffs only after adding explicit billing-period and tier-allocation assumptions.
- [Implemented] Report annual supplied volume, sewer-eligible supplied volume, gross savings, maintenance and energy cost, net savings, simple and discounted payback, replacement cost, NPV, and IRR.
- [Implemented] Include units and assumptions in screen and exported results and distinguish user inputs from calculated outputs.
- [Implemented] Validate negative costs, zero or inconsistent tariff units, non-positive net savings, and payback cases that display as not achieved rather than divide by zero.
- [Implemented] Deterministic tests reconcile economic outputs to delivered hydraulic totals and tariff units, including mixed indoor/irrigation demand and municipal-backup scenarios.

## Payback-driven indirect-system optimization

Add an optimization workflow for indirect systems that can minimize simple payback while sizing the primary tank, filtration pump, and buffer tank together. These variables interact: primary storage controls available rainwater, the filtration pump controls buffer refill rate, and the buffer tank serves peak end-use demand. The least-cost or shortest-payback values therefore cannot be selected reliably in isolation.

**Implemented:** Analysis settings includes a deterministic exhaustive search using an editable, explicitly illustrative catalog with three initial choices for each component. Users can bulk-edit catalog names, capacities, installed costs, and pump power; choose simple payback, net annual savings, rainwater reliability, analysis-period net benefit, or lifecycle NPV as the objective; and constrain minimum reliability, maximum annual municipal makeup, maximum installed cost, and positive net savings. The workflow reuses the hourly indirect-system and lifecycle financial inputs, estimates filtration-pump energy, and saves its inputs with the project.

The objective should be based on complete lifecycle drivers rather than hydraulic performance alone:

```text
simple payback
  = (installed cost - incentives)
    / (annual utility savings - annual maintenance - annual energy cost)
```

Before optimization is enabled, add component cost curves for primary tanks, filtration pumps, and buffer tanks; pump head and efficiency; electricity tariffs; component-specific maintenance; and replacement assumptions. Without size-dependent costs and energy, an optimizer would incorrectly favor oversized equipment whenever it produces even a small increase in rainwater delivery.

The optimizer should minimize payback subject to explicit engineering constraints, including:

- Minimum rainwater reliability or annual rainwater supply.
- Maximum municipal makeup.
- Required peak end-use flow.
- Maximum buffer refill time.
- Minimum primary-tank operating level.
- Maximum equipment footprint or available tank volume.
- Acceptable pump cycling and water residence time.
- Positive net annual savings; otherwise payback is not achieved.

A brute-force search can become expensive because candidate counts multiply. For example, 30 primary tank sizes, 15 filtration-pump sizes, and 15 buffer-tank sizes require 6,750 full hourly simulations. Use a staged, coarse-to-fine workflow instead:

1. Run the daily model across primary-tank sizes and remove clearly uneconomic or hydraulically unsuitable capacities.
2. Retain a small group near the reliability and savings knee.
3. Derive feasible filtration-pump ranges from peak flow and refill-time requirements.
4. Eliminate buffer sizes that cannot satisfy peak-period demand.
5. Run aggregate-only hourly simulations for the surviving combinations.
6. Run detailed timestep simulations only for shortlisted designs.
7. Refine the search around the best candidates and report nearby alternatives rather than only one winner.

[Partially implemented] Rainfall collection, hourly demand, and calendar arrays are precomputed and retained in a bounded cache for unchanged runs. Optimization candidates use an aggregate-only hourly evaluator that avoids timestep dictionaries and DataFrames while returning supply, municipal makeup, overflow, pump energy inputs, reliability, costs, savings, and payback. Candidate-result caching, parallel worker processes, cancellation, constraint-based early stopping, and detailed simulation of shortlisted designs remain planned.

A genetic algorithm may help after the design space expands to additional continuous and discrete variables such as pump head, efficiency, refill controls, minimum operating level, tariff structures, catalog equipment, replacement schedules, and energy costs. For only three moderately sized variables, a deterministic coarse-to-fine grid remains easier to validate, explain, and reproduce.

The recommended long-term method is hybrid:

1. Apply engineering rules to eliminate infeasible designs.
2. Run a coarse deterministic grid.
3. Seed a genetic algorithm with the best feasible grid candidates.
4. Run detailed simulations for the best genetic candidates.
5. Perform a deterministic local grid search around the best result.
6. Present the shortest-payback design alongside several near-optimal alternatives and their hydraulic tradeoffs.

Genetic results do not prove a global optimum. Save the random seed, population size, generation count, mutation and crossover settings, constraints, convergence history, cost-model version, and simulation-input signature so every optimization is auditable and reproducible. Add deterministic benchmark problems where the known grid optimum can be compared with the genetic and hybrid results.

## First-flush diversion and event losses

The initial explicit first-flush model is implemented using the rainfall-history criterion favored by Khan (2026). Each collection surface has a unit-aware diversion depth, and a project-wide antecedent dry period identifies new events. Diversion occurs only on the event's first wet observation; consecutive wet observations do not divert again. Daily and hourly results keep gross runoff, first-flush loss, and net collection separate.

Implementation requirements include:

- [Implemented] Add first-flush depth to collection-surface parameters, with automatic English (I-P) and Metric (SI) conversion.
- [Implemented] Define a rainfall event using a configurable antecedent dry period. Consecutive wet observations within the same event do not trigger another diversion.
- [Implemented] Divert up to the configured depth on the first wet observation only; unused depth does not carry into a consecutive wet observation.
- [Implemented per surface] Multiple surfaces have independent diverter allowances. A shared downstream diverter remains planned.
- [Implemented] Keep first-flush loss separate from runoff coefficient, filter loss, tank overflow, and net collection in calculations and reports.
- [Partially implemented] Report diverted volume by timestep and full analysis period, with event identifiers retained in results. Dedicated event and yearly summary tables remain planned.
- [Implemented] Add tests for rainfall below the diversion threshold, multi-timestep storms, storms spanning midnight, dry-period reset, zero diversion, and persistence compatibility.

## Unusable tank volume and operating levels

The first minimum-operating-level implementation is complete for primary tanks. The simulation distinguishes physical tank capacity from water available for normal withdrawal, and the setting remains separate from initial fill.

Implementation requirements include:

- [Implemented as percentage of capacity] Add a minimum operating level normalized internally to volume. Absolute-volume entry remains planned.
- [Implemented] Prevent normal demand and pump withdrawals from reducing tank level below the minimum operating volume while still including that water in the displayed physical tank level.
- Define whether emergency withdrawal, maintenance drain-down, and overflow calculations use total or usable capacity.
- Apply the same concept consistently to primary and buffer tanks where configured.
- Report total capacity, unusable volume, usable capacity, physical water level, usable water available, and unmet demand attributable to the operating limit.
- Migrate existing projects with zero unusable volume so prior results remain unchanged.
- Add boundary tests for empty, partially filled, exactly-at-minimum, full, and oversized minimum-volume configurations.

## Candidate tank performance comparison

The reliability curve now includes an auditable, sortable, and CSV-exportable performance row for every candidate tank size. In addition to reliability, each row includes total demand, rainwater supplied, unmet demand, municipal makeup, system unmet demand, overflow, first-flush loss, other treatment losses, and final storage. Economic analysis adds annual savings and payback columns when its inputs are configured.

Implementation requirements include:

- [Implemented] Extend the reliability-curve engine to aggregate the same mass-balance outputs used by the selected-tank simulation rather than running a separate simplified interpretation.
- Preserve cancellation and progress reporting because additional candidate metrics increase calculation cost.
- [Implemented] Add a sortable/exportable comparison table and allow users to promote a candidate to the primary tank without re-entering its size.
- [Implemented] Add a recommendation aid that identifies diminishing reliability gains, exposes the threshold as a user-controlled assumption, and avoids presenting it as a universally optimal tank size.
- [Implemented] Include candidate hydraulic metrics in saved analysis results and invalidate them when rainfall, demand, loss, operating-level, or system inputs change. Economic columns are recalculated from the saved annual supply when financial inputs change.
- [Implemented] Add reconciliation tests proving that each candidate row matches an independent simulation of the same tank size.

## Multi-site weather comparison

[Implemented] A **Multi-site comparison** sub-tab under **Rainwater Data** provides NOAA Quick Access-style state browsing and a nationwide station-name search for fixed 1991-2020 precipitation normals. A clustered, navigable OpenStreetMap view shows the applicable NOAA stations without slowing broad-zoom interaction. Users can add multiple stations to a comparison showing annual and meteorological-season precipitation in the project's current inches or millimeters setting, then export the table to CSV. Values are water equivalent; snowfall depth is intentionally excluded to prevent unlike quantities from being combined.

The comparison is session-only and does not replace project rainfall or invalidate simulation results. An on-screen disclaimer explains that the simulation average may differ because its station, observation period, precipitation basis, completeness, or provider processing can differ. Network requests run off the Tkinter UI thread, and provider responses, city ranking, station-ID lookup, and comparison ordering have focused tests.

Future work may add preliminary roof-area and runoff-coefficient screening, saved comparison sets, and a deliberate action for copying selected location metadata into a project. Keep these estimates separate from simulated collection, demand satisfaction, storage reliability, first-flush losses, and overflow.

## Multi-project comparison report

[Not started] Add a separate report type named **Multi-project comparison report**. It should let users select multiple rainwater project database files, choose a project from each file when necessary, and compare them without changing or overwriting the project currently open in the desktop application.

The report should normalize displayed units and compare the inputs and most recent saved results that are meaningful across projects, including location and rainfall provenance, collection area, average annual precipitation, runoff assumptions, demand, selected tank size, annual rainwater supplied, reliability, municipal makeup, overflow, first-flush and treatment losses, economics, and major review conditions. Missing, stale, incompatible, or never-run analysis results must be identified rather than silently recalculated or treated as zero.

Implement the report through the shared validated report-model and renderer architecture, with HTML, LaTeX, and direct-PDF output following the same accessibility and portability requirements as single-project reports. Include a concise comparison table, clearly labelled project-specific assumptions, and charts only where units, analysis periods, and metrics are genuinely comparable. Project files must be opened read-only for comparison, schema compatibility must be validated, and tests should cover different unit systems, rainfall periods, schema versions, duplicate project names, missing files, and partial results.

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
