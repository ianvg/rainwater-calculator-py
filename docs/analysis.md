# Analysis and results

When an analysis has already been run, the calculator records a fingerprint of the rainfall and simulation inputs used for that run. If rainfall, collection surfaces, demand, tank parameters, or reliability-curve settings change, opening the **Results** tab displays a warning that the analysis must be run again. Project metadata such as the name, address, coordinates, and display units does not invalidate an analysis.

The results table contains every simulated daily record. Use its vertical scrollbar to move from the beginning to the end of the analysis period and its horizontal scrollbar to inspect all result columns.

The analysis simulates storage behavior through the rainfall record for a range of tank sizes.

## Analysis settings

Review the minimum and maximum tank size, graph step, initial storage assumptions, and any other available settings. Units are displayed next to numeric fields.

The **Daily demand schedule** selects how many days per week recurring daily demand applies. A five-day schedule applies daily and occupancy-based demand Monday through Friday; monthly end-use totals remain distributed across every day of the month. Existing projects default to seven days per week.

Enable automatic graph step sizing to divide the tank-size range into approximately 40 steps. For example, a 20,000-gallon range uses a 500-gallon step.

## Run the analysis

Select **File > Run analysis** or press `Ctrl+R`. The status area reports the current analysis part and progress.

If analysis cannot start, check that rainfall data has been imported and that required numeric values are valid and positive.

## Reliability curve

The reliability curve compares tank size with the percentage of demand satisfied by the simulated system. Hover near chart points to inspect values. Tick marks help compare neighboring tank sizes.

Increasing tank size generally improves reliability until collection or demand becomes the limiting factor. The curve should be interpreted together with project cost, available space, overflow, required backup supply, and design criteria.

## Tank water over time

The tank-water chart shows simulated storage through the rainfall period for the selected tank size. Point markers can be hidden when the record is dense, leaving a clearer line chart.

## Saved results

Completed results are stored when the project is saved. Reopening the project restores the results and charts without rerunning the analysis. Rerun the analysis after changing relevant rainfall, demand, surface, unit, or tank settings.
