# Analysis and results

When an analysis has already been run, the calculator records a fingerprint of the rainfall and simulation inputs used for that run. If rainfall, collection surfaces, demand, tank parameters, or reliability-curve settings change, opening the **Results** tab displays a warning that the analysis must be run again. Project metadata such as the name, address, coordinates, and display units does not invalidate an analysis.

## Compare tank sizes

Open **Analysis settings**, immediately to the left of **Results**, to configure the reliability-curve range, primary tank, initial fill, and minimum operating level. Add one or more sizes to **Tank size comparison** and run the analysis. The table reports demand reliability for every comparison size, including sizes that do not fall on the regular graph step. Comparison sizes are saved with the project.

Select **Multi-tank comparison** to enable the tank-size comparison controls. The controls remain disabled when this option is clear. Existing comparison sizes remain saved while disabled but are excluded from multi-tank analysis and output.

The primary tank controls the detailed daily tank-level results, report tank summary, and selected marker on the reliability curve. Double-click a comparison row, or select it and choose **Use as primary**, to make that size the primary tank. Changing comparison sizes invalidates the saved analysis until it is run again.

## Results views

The **Results** tab contains horizontal **Single-tank summary** and **Multitank summary** sub-tabs. Single-tank summary shows the primary tank's reliability curve, daily storage, distribution, yearly reliability, and result rows. Multitank summary overlays every tank entered in **Tank size comparison** on three charts: tank water over time, tank-level distribution, and yearly demand reliability. Tank-level distributions use six percentage-of-capacity bins so different tank sizes can be compared on the same scale.

Comparison simulations are saved with completed project analysis and restored when the project is reopened. Add at least two comparison sizes and run the analysis to compare multiple tanks together.

Changing only the project unit system does not require another analysis. Simulation values are stored in consistent internal units, and Results converts the saved tables and charts for display. When Results is opened after such a change, the application reports that the units were converted. Changes to physical or simulation parameters still require a rerun.

The results table contains every simulated daily record. Use its vertical scrollbar to move from the beginning to the end of the analysis period and its horizontal scrollbar to inspect all result columns.

The analysis simulates storage behavior through the rainfall record for a range of tank sizes.

## Analysis settings

Review the minimum and maximum tank size, graph step, initial storage assumptions, and any other available settings. Units are displayed next to numeric fields.

The **Daily demand schedule** selects how many days per week recurring daily demand applies. A five-day schedule applies daily and occupancy-based demand Monday through Friday; monthly end-use totals remain distributed across every day of the month. Existing projects default to seven days per week.

Enter the desired **Number of steps** and select **Auto** to divide the tank-size range into that many increments. New projects default to 20 steps. The selected count is stored with the project.

## Run the analysis

Select **Run analysis > Run single-tank analysis** or press `Ctrl+R` to analyze the primary tank without running the comparison tanks. Select **Run analysis > Run multi-tank analysis** or press `Ctrl+Alt+R` to analyze the primary tank and every enabled comparison size. Multi-tank analysis requires **Multi-tank comparison** to be enabled and at least one comparison size. The status area reports the current analysis part and progress.

While an analysis is running, select **Cancel analysis** beside the bottom progress bar to interrupt it. Cancellation is checked throughout reliability-curve and individual tank simulations. Any previous completed results remain available; partial results from the cancelled run are discarded.

When an hourly schedule is enabled, the primary-tank analysis also produces hourly component results. Open **Results > Hourly results** and select a year to inspect hourly storage, demand, pump and filter flow, municipal makeup, rainwater shortfall, and overflow. The year selector prevents long weather records from overloading the results table while the complete hourly record remains stored in the project.

If analysis cannot start, check that rainfall data has been imported and that required numeric values are valid and positive.

## Reliability curve

The reliability curve compares tank size with the percentage of simulated calendar days on which the system can provide 100% of that day's water demand. For each day, the simulation compares the water available in the tank immediately before withdrawal with the full daily demand. A day is reliable when the available water is greater than or equal to that demand. Reliability is calculated as:

`reliability (%) = days with 100% of daily demand met / total simulated days x 100`

Days with zero demand count as days whose complete demand was met. The minimum operating level reduces the water available for normal withdrawal and therefore can affect reliability. Hover near chart points to inspect values. Tick marks help compare neighboring tank sizes.

The complete collection, demand, storage, overflow, withdrawal, and conservation procedure is documented in [Daily analysis formulas and mass balance](daily-analysis-method.md).

Increasing tank size generally improves reliability until collection or demand becomes the limiting factor. The curve should be interpreted together with project cost, available space, overflow, required backup supply, and design criteria.

## Tank water over time

The tank-water chart shows one calendar year of simulated storage for the selected tank size. Use the left and right controls to move through the available years, or type an available year in the year field and press `Enter`. Point markers can be hidden when the record is dense, leaving a clearer line chart.

## Yearly demand reliability

The yearly demand reliability chart is a 100% stacked bar chart. Each bar represents one calendar year and divides its simulated days into days when the complete daily demand was met by rainwater and days when it was not. The two percentages always sum to 100%. Hover over a bar segment to inspect the yearly day counts and percentages.

## Saved results

Completed results are stored when the project is saved. Reopening the project restores the results and charts without rerunning the analysis. Rerun the analysis after changing relevant rainfall, demand, surface, or tank settings; display-unit changes are converted without rerunning.
