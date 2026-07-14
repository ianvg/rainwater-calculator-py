# Rainfall data

The analysis uses daily precipitation records. Longer, representative periods generally provide a more meaningful reliability estimate than short records.

## Import from ACIS

Set the project country to **USA - United States** to use ACIS importing.

Open the rainwater-data import tab and select a state. Begin typing a state name to move to the first matching option.

Select **Total precipitation** to use the ACIS daily precipitation value. ACIS does not provide a native rain-only field, so **Rain only** excludes precipitation on days with reported snowfall. This conservative approximation can undercount rain on mixed rain and snow days; the application displays a warning after such an import.

After stations are retrieved, type the first few letters of a station name to preselect a matching station. Choose the date range and import the record.

While the application searches the weather service for stations, the lower-right progress bar animates and the station-selection controls remain disabled until the search finishes.

ACIS importing requires an internet connection. After a successful import, the rainfall summary identifies the station name, station ID, number of rows, and record dates. Station information is retained when the project is saved and reopened.

## Import Canadian climate data

Set the project country to **CAN - Canada**. The import tab changes to the Environment and Climate Change Canada (ECCC) workflow.

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

Review the rainfall summary after importing. Confirm that the date range, row count, units, and source are reasonable before running an analysis.

## Data checks

- Dates should be valid and unambiguous.
- Each row should represent one day.
- Precipitation values should use the expected source units.
- Missing or duplicate dates should be investigated.
- Negative precipitation values are not valid.

!!! warning
    A successful import does not guarantee that a rainfall record is complete or appropriate for the project location. Validate the source record independently.
