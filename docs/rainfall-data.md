# Rainfall data

The analysis uses daily precipitation records. Longer, representative periods generally provide a more meaningful reliability estimate than short records.

## Import from ACIS

Open the rainwater-data import tab and select a state. Begin typing a state name to move to the first matching option.

After stations are retrieved, type the first few letters of a station name to preselect a matching station. Choose the date range and import the record.

ACIS importing requires an internet connection. After a successful import, the rainfall summary identifies the station name, station ID, number of rows, and record dates. Station information is retained when the project is saved and reopened.

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
