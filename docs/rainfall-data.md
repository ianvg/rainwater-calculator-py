# Rainfall data

## Compare annual and seasonal precipitation at multiple U.S. sites

Open **Rainwater Data > Multi-site comparison** to compare NOAA 1991-2020 annual and seasonal precipitation normals without changing the daily rainfall assigned to the current project. Select a state to browse its stations, or type in **Find station by name** to search station names across the entire United States. While a name search contains text, state selection is disabled; clear the search to browse by state again. Select a station and add it to the comparison. Each selected station becomes one row with Annual, Winter, Spring, Summer, and Autumn values. The initial order is highest to lowest annual precipitation. Select the Station heading to sort names alphabetically, or select any precipitation heading to sort by that period; select the same heading again to reverse the order. The arrow on the active heading indicates the direction. The current table order is retained in CSV exports. Use the page scrollbar or the mouse wheel outside the map and selection lists to move between the station browser, map, and comparison table; the table also has its own vertical and horizontal scrollbars.

Values use the project's current precipitation unit (inches or millimeters) and represent water equivalent. They include rain and the liquid-water equivalent of frozen precipitation. Winter is December-February, Spring is March-May, Summer is June-August, and Autumn is September-November. These are not rain-only totals, and snowfall depth must not be added to or subtracted from them.

The station browser uses NOAA Quick Access station names and identifiers joined to NOAA's GHCN-D station inventory for coordinates. Its navigable map uses OpenStreetMap tiles and groups nearby stations at broad zoom levels for responsiveness. Select a cluster to zoom closer. Annual and seasonal precipitation values come from NOAA NCEI's [U.S. Climate Normals Quick Access](https://www.ncei.noaa.gov/access/us-climate-normals/#dataset=normals-annualseasonal&timeframe=30) dataset and use the fixed 1991-2020 normal period. The station catalog is cached locally for 30 days, and retrieved station values are cached for one year. Requests reuse the NOAA connection when possible, suppress duplicate lookups for a station already loading, and report the status of a single automatic retry when NOAA is slow or unavailable.

The official 54.2 MB NOAA annual/seasonal bulk archive is optional. It can be selected while installing the Windows application or downloaded later by selecting the information icon beside the **Multi-site comparison** subtab. That dialog also contains the comparison overview, planning-data disclaimer, and NOAA source link. When installed, the station catalog and uncached annual-normal lookups are read locally from the archive; the online NOAA services remain the fallback when it is absent. The archive section can remove the archive and recover its disk space. Removing it retains ordinary cached station values and does not affect projects or imported rainfall.

This comparison is a preliminary screening tool, not simulation input. Project simulations use imported daily rainfall, which may come from a different station, observation period, precipitation basis, or provider-processing method. Consequently, the average annual precipitation shown after a simulation may differ from the Climate Normals comparison value. Adding or removing comparison rows does not modify the current project or invalidate its results.

## Find stations near project coordinates

When project latitude and longitude are available, select **Find Nearest 10** to search geographically around the project. The calculator expands the search area as needed, ranks stations by great-circle distance, and displays the nearest ten stations that overlap the requested historical period. Distances are shown in kilometres, and the resulting stations can be selected, mapped, and imported through the normal workflow. This search does not require a State or Province/Territory selection.

The analysis uses daily precipitation records. Longer, representative periods generally provide a more meaningful reliability estimate than short records.

## Import from ACIS

Set the project country to **USA - United States** to use ACIS importing.

The source is the NOAA Regional Climate Centers' [Applied Climate Information System (ACIS)](https://www.rcc-acis.org/). The calculator imports daily station records containing observation dates and precipitation in inches.

Open the rainwater-data import tab and select a state. Begin typing a state name to move to the first matching option.

Select **Total precipitation** to use the ACIS daily precipitation value. ACIS does not provide a native rain-only field, so **Rain only** excludes precipitation on days with reported snowfall. This conservative approximation can undercount rain on mixed rain and snow days; the application displays a warning after such an import.

After stations are retrieved, type the first few letters of a station name to preselect a matching station. Choose the date range and import the record.

While the application searches the weather service for stations, the lower-right progress bar animates and the station-selection controls remain disabled until the search finishes.

After a station search completes, the map in the lower half of the tab displays every returned station that has valid coordinates and adjusts its view to include them. Nearby stations are grouped into numbered markers when zoomed out and separate automatically as the map is enlarged. Select a grouped marker to zoom into it. The selected station or group is red; other markers are blue. Select an individual marker to select the corresponding station in the dropdown, or select a station in the dropdown to highlight its marker. Map tiles require an internet connection and are provided by OpenStreetMap.

ACIS importing requires an internet connection. After a successful import, the rainfall summary identifies the station name, station ID, number of rows, and record dates. Station information is retained when the project is saved and reopened.

## Import Canadian climate data

Set the project country to **CAN - Canada**. The import tab changes to the Environment and Climate Change Canada (ECCC) workflow.

The source is [ECCC Historical Climate Data](https://climate.weather.gc.ca/). The calculator imports daily station observations containing dates and precipitation in millimetres.

1. Select a province or territory.
2. Select whether to use **Total precipitation** or **Rain only**.
3. Find and select an ECCC climate station.
4. Import the selected station.

With the station dropdown focused or expanded, type up to four letters in quick succession to move to the first station whose name begins with that prefix. The expanded list scrolls to keep the highlighted station visible. The prefix resets after one second or after the fourth character.

**Total precipitation** includes liquid precipitation and the water equivalent represented by snowfall observations. This may be appropriate when snow is retained and later melts into the collection system. **Rain only** excludes snowfall and may be more appropriate where snow is expected to blow, slide, or be removed from the collection surface. Select the basis that matches the roof, climate, and operating assumptions.

ECCC values are provided in millimetres and are converted automatically into the calculator's internal rainfall units. The application follows all API result pages and completes the requested daily calendar. Missing daily values are treated as zero precipitation so water demand is still simulated for those days; a warning reports how many values were missing.

## Import a CSV file

Choose the CSV import action and select a rainfall file. The standard input contains:

| Column | Meaning |
| --- | --- |
| `Date` | Observation date |
| `Precipitation` | Daily precipitation amount |

Header capitalization and surrounding spaces are ignored, and additional columns are allowed. Use one row per day and preferably format dates as `YYYY-MM-DD`. Precipitation must be numeric and use inches for an English (I-P) project or millimetres for a Metric (SI) project. Blank or nonnumeric precipitation values are treated as zero by the simulation but retained in the quality metadata as missing observations.

```csv
Date,Precipitation
2025-01-01,0.00
2025-01-02,0.37
2025-01-03,0.00
```

Review the rainfall summary after importing. Confirm that the date range, row count, units, and source are reasonable before running an analysis.

## Quality and provenance

The **Quality and provenance** panel scores coverage against every calendar day in the complete years spanned by the record. This deliberately counts unobserved days before the first observation and after the last observation in a boundary year, so a partial year cannot appear complete. The panel reports observed and expected days, missing days grouped into continuous periods, partial or incomplete years, and duplicate dates. Provider-reported missing values and nonnumeric CSV precipitation values remain identified as missing even when the daily simulation substitutes zero precipitation.

Classify a user-supplied record as **Observed station data**, **Synthetic rainfall data**, **Interpolated rainfall data**, **Gridded reanalysis data**, or leave it explicitly unclassified. Record the temporal resolution and source timezone; an IANA timezone such as `America/Toronto` is preferred when it is known. These fields describe provenance and do not convert or resample the rainfall. The current calculation engine expects daily totals and reports a review warning if the record is labeled with another resolution.

ACIS and ECCC imports are automatically labeled as observed daily station data. Because their current import responses do not provide a dependable UTC offset, the timezone is recorded as station-local with the missing offset disclosed. Generating Hyetos-style profiles preserves the classification of the source daily totals and separately labels the within-day timing as synthetic.

## Generate synthetic hourly rainfall

After loading or importing a daily record, open **Rainwater Data > Hourly data**, select **Generate Synthetic Hourly Rainfall**, and enter a random seed. The same daily record and seed always produce the same result. The generator uses a Hyetos-style workflow: Bartlett-Lewis rectangular pulses produce candidate within-day hyetographs, a repetition step selects a plausible candidate, and an adjusting step scales the 24 hourly depths so their sum exactly matches each observed daily total. The Hourly data tab documents these assumptions, displays generation and usage status, and provides a 24-hour record-wide distribution preview. Generating profiles automatically selects **Use generated synthetic hourly rainfall** under **Analysis settings**.

Daily tank analyses continue to use the original daily totals. When **Use generated synthetic hourly rainfall** is selected, hourly analyses use the generated timing directly, including the timing of collection, overflow, and first-flush diversion. Turn the option off to retain the generated profiles but make hourly analysis use the legacy assumption that the day's precipitation arrives at 23:00. Use **Remove Generated Profile** to discard only the derived hourly columns and return to the daily-timing assumption; the imported daily totals and their source classification remain intact. The setting and generated profiles are retained when the project is saved.

The built-in stochastic parameters are general-purpose defaults, not a local calibration. For design work that depends on peak intensities or storm duration, calibrate the Bartlett-Lewis parameters against representative observed hourly data and validate the generated statistics independently.

## Data checks

- Dates should be valid and unambiguous.
- Each row should represent one day.
- Precipitation values should use the expected source units.
- Missing or duplicate dates should be investigated.
- Negative precipitation values are not valid.

!!! warning
    A successful import does not guarantee that a rainfall record is complete or appropriate for the project location. Validate the source record independently.
